//! Recording capacity policy; never deletes files or commands hardware.
use std::io;
use std::path::Path;

pub const RESERVE_BYTES: u64 = 32 * 1024 * 1024;
pub const RESERVE_INODES: u64 = 128;
pub const FILE_LIMIT_BYTES: u64 = 128 * 1024 * 1024;

pub struct Budget {
    headroom: u64,
    written: u64,
}
impl Budget {
    pub fn new() -> Self {
        Self {
            headroom: 0,
            written: 0,
        }
    }
    pub fn refresh(&mut self, available: u64, inodes: u64) -> io::Result<()> {
        self.headroom = 0;
        if available <= RESERVE_BYTES || inodes <= RESERVE_INODES {
            return Err(io::Error::other(
                "CSV reserve reached (32 MiB / 128 inodes); export recordings and free space manually",
            ));
        }
        self.headroom = available - RESERVE_BYTES;
        Ok(())
    }
    pub fn consume(&mut self, bytes: usize) -> io::Result<()> {
        let bytes = bytes as u64;
        if bytes > self.headroom || bytes > FILE_LIMIT_BYTES.saturating_sub(self.written) {
            return Err(io::Error::other(
                "CSV capacity/file limit reached; recordings retained, logging stopped",
            ));
        }
        self.headroom -= bytes;
        self.written += bytes;
        Ok(())
    }
}

#[cfg(any(target_os = "linux", test))]
fn validate_mounts(mounts: &str) -> io::Result<()> {
    fn entry<'a>(mounts: &'a str, path: &str) -> Option<Vec<&'a str>> {
        // Last occurrence handles stacked mounts conservatively with the normal
        // kernel listing order. Runtime device checks also reject nested tmpfs.
        mounts
            .lines()
            .filter_map(|line| {
                let fields: Vec<_> = line.split_whitespace().collect();
                (fields.len() >= 10 && fields[4] == path).then_some(fields)
            })
            .last()
    }
    fn writable_ext4(fields: &[&str]) -> bool {
        let Some(separator) = fields.iter().position(|v| *v == "-") else {
            return false;
        };
        fields.get(separator + 1) == Some(&"ext4")
            && fields[5].split(',').any(|v| v == "rw")
            && fields
                .get(separator + 3)
                .is_some_and(|v| v.split(',').any(|v| v == "rw"))
    }
    if let (Some(state), Some(var)) = (entry(mounts, "/state"), entry(mounts, "/var")) {
        if writable_ext4(&state)
            && writable_ext4(&var)
            && state[2] == var[2]
            && state[3] == "/"
            && var[3] == "/var"
        {
            return Ok(());
        }
    }
    Err(io::Error::other(
        "CSV requires writable DATA-backed /state and /var bind; refusing volatile recording",
    ))
}

/// Linux requires the pinned MixOS DATA bind; errors never fall back to tmpfs.
#[cfg(target_os = "linux")]
pub fn probe(directory: &Path) -> io::Result<(u64, u64)> {
    use std::os::unix::{ffi::OsStrExt, fs::MetadataExt};
    validate_mounts(&std::fs::read_to_string("/proc/self/mountinfo")?)?;
    if std::fs::metadata(directory)?.dev() != std::fs::metadata("/state")?.dev() {
        return Err(io::Error::other(
            "CSV directory is not on the state filesystem",
        ));
    }
    let path = std::ffi::CString::new(directory.as_os_str().as_bytes())
        .map_err(|_| io::Error::other("invalid CSV directory"))?;
    let mut stats = std::mem::MaybeUninit::<libc::statvfs>::uninit();
    // SAFETY: path is NUL-terminated, stats is writable; only read after success.
    let result = unsafe { libc::statvfs(path.as_ptr(), stats.as_mut_ptr()) };
    if result != 0 {
        return Err(io::Error::last_os_error());
    }
    let stats = unsafe { stats.assume_init() };
    let bytes = (stats.f_bavail as u64)
        .checked_mul(stats.f_frsize as u64)
        .ok_or_else(|| io::Error::other("CSV free-space counter overflow"))?;
    Ok((bytes, stats.f_favail as u64))
}

#[cfg(not(target_os = "linux"))]
pub fn probe(_directory: &Path) -> io::Result<(u64, u64)> {
    // Host/mock recordings retain the file cap without claiming DATA persistence.
    Ok((u64::MAX, u64::MAX))
}

#[cfg(test)]
mod tests {
    use super::*;
    const MOUNTS: &str = "10 1 8:2 / /state rw,noatime - ext4 /dev/mmcblk1p1 rw\n11 1 8:2 /var /var rw,noatime - ext4 /dev/mmcblk1p1 rw\n";
    #[test]
    fn data_bind_must_be_writable_ext4_on_same_device() {
        assert!(validate_mounts(MOUNTS).is_ok());
        assert!(validate_mounts(&MOUNTS.replace("11 1 8:2", "11 1 0:9")).is_err());
        assert!(validate_mounts(&MOUNTS.replace("ext4", "tmpfs")).is_err());
        assert!(validate_mounts(&MOUNTS.replace("/var rw,", "/var ro,")).is_err());
        assert!(validate_mounts(&MOUNTS.replace("/state rw,", "/state ro,")).is_err());
        assert!(validate_mounts("garbled\n").is_err());
        assert!(
            validate_mounts(&MOUNTS.replace("/dev/mmcblk1p1 rw", "/dev/mmcblk1p1 ro")).is_err()
        );
        assert!(validate_mounts(&MOUNTS.replace("rw,noatime -", "rw,noatime shared:12 -")).is_ok());
        assert!(validate_mounts(&MOUNTS.replace("8:2 /var /var", "8:2 /other /var")).is_err());
    }
    #[test]
    fn byte_and_inode_reserves_fail_closed() {
        let mut budget = Budget::new();
        assert!(budget.refresh(RESERVE_BYTES, 1000).is_err());
        assert!(budget.refresh(RESERVE_BYTES + 100, RESERVE_INODES).is_err());
        budget
            .refresh(RESERVE_BYTES + 100, RESERVE_INODES + 1)
            .unwrap();
        budget.consume(60).unwrap();
        assert!(budget.consume(41).is_err());
        budget.consume(40).unwrap();
        assert!(budget.consume(1).is_err());
    }
    #[test]
    fn failed_probe_invalidates_remaining_budget() {
        let mut budget = Budget::new();
        budget.refresh(RESERVE_BYTES + 1000, 1000).unwrap();
        assert!(budget.refresh(RESERVE_BYTES, 1000).is_err());
        assert!(budget.consume(1).is_err());
        budget.refresh(RESERVE_BYTES + 100, 1000).unwrap();
        budget.consume(100).unwrap();
    }
    #[test]
    fn refreshed_space_does_not_reset_file_limit() {
        let mut budget = Budget::new();
        assert!(budget.consume(1).is_err());
        budget.refresh(u64::MAX, u64::MAX).unwrap();
        budget.consume(FILE_LIMIT_BYTES as usize - 1).unwrap();
        budget.refresh(u64::MAX, u64::MAX).unwrap();
        budget.consume(1).unwrap();
        assert!(budget.consume(1).is_err());
    }
}
