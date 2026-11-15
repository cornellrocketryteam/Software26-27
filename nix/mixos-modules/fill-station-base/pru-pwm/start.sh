#!/bin/sh
# Arguments keep sysfs isolated for host tests; production always passes /sys.
set -eu
sysfs=$1
cores=$2
application=$3
attempts=${PRU_PWM_WAIT_ATTEMPTS:-100}

fail() { echo "PRU PWM startup: $*" >&2; exit 1; }
for module in pruss irq-pruss-intc pru_rproc rpmsg_ctrl rpmsg_char; do
    modprobe "$module"
done

for core in $cores; do
    case "$core" in
        0) address=30034000; port=30; hexport=0x1e ;;
        1) address=30038000; port=31; hexport=0x1f ;;
        *) fail "unsupported core $core" ;;
    esac
    firmware="fill-station-pru0_${core}-fw"
    remote=
    count=0
    while [ "$count" -lt "$attempts" ]; do
        for candidate in "$sysfs"/class/remoteproc/remoteproc*; do
            [ -f "$candidate/name" ] || continue
            [ "$(cat "$candidate/name")" = "$address.pru" ] || continue
            resolved=$(readlink -f "$candidate")
            case "$resolved" in
                */30000000.icssg/"$address.pru"/remoteproc/*) ;;
                *) fail "remoteproc $address has unexpected device identity" ;;
            esac
            [ -z "$remote" ] || fail "duplicate remoteproc identity $address"
            remote=$candidate
        done
        [ -z "$remote" ] || break
        sleep 0.1
        count=$((count + 1))
    done
    [ -n "$remote" ] || fail "remoteproc $address did not appear"
    state=$(cat "$remote/state")
    case "$state" in
        running)
            [ "$(cat "$remote/firmware")" = "$firmware" ] || fail "$address runs foreign firmware; refusing replacement"
            ;;
        offline)
            printf '%s\n' "$firmware" > "$remote/firmware"
            printf 'start\n' > "$remote/state"
            ;;
        *) fail "$address has unexpected remoteproc state $state" ;;
    esac

    ready=false
    count=0
    while [ "$count" -lt "$attempts" ]; do
        if [ "$(cat "$remote/state")" = running ]; then
            for service in "$sysfs"/bus/rpmsg/devices/*; do
                [ -f "$service/name" ] || continue
                [ "$(cat "$service/name")" = rpmsg-raw ] || continue
                case "$(cat "$service/dst")" in "$port"|"$hexport") ;; *) continue ;; esac
                resolved=$(readlink -f "$service")
                case "$resolved" in
                    */30000000.icssg/"$address.pru"/*) ready=true ;;
                esac
            done
        fi
        [ "$ready" = false ] || break
        sleep 0.1
        count=$((count + 1))
    done
    [ "$ready" = true ] || fail "$address matching RPMsg endpoint did not become ready"
done
exec "$application"
