"""Regenerate real nanopb/Python codecs; verify old/new wire compatibility locally.

Run codec tests with: uv run --with grpcio-tools==1.76.0 --with protobuf==6.33.0
python -m unittest discover -s tests -p test_source_metadata.py
No hardware, broker or configured database is contacted.
"""
import ctypes
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILL = ROOT/'fill-station'
ADDED = {
 'source_metadata_version':67,'publisher_session_hi':68,'publisher_session_lo':69,
 'publisher_sequence':70,'source_monotonic_ms':71,'source_unix_ms':72,
 'source_unix_valid':73,'source_time_quality':74,'adc1_sample_age_ms':75,
 'adc1_sample_age_valid':76,'adc2_sample_age_ms':77,'adc2_sample_age_valid':78,
 'fsw_receive_age_ms':79,'fsw_receive_age_valid':80,'source_time_generation':81,
}

class SourceSchema(unittest.TestCase):
    def test_schema_copies_match_with_new_unique_tags_and_legacy_fields_retained(self):
        source=(FILL/'proto/telemetry.proto').read_text()
        self.assertEqual(source,(ROOT/'ground-station/proto/telemetry.proto').read_text())
        fields=re.findall(r'\b(\w+)\s+(\w+)\s*=\s*(\d+)\s*;',source)
        by_name={name:(kind,int(tag)) for kind,name,tag in fields}
        self.assertEqual(len(fields),len({tag for _,_,tag in fields}))
        self.assertEqual(by_name['ms_since_boot_fill'],('uint64',63))
        self.assertEqual(by_name['valid_readings_mask'],('uint32',66))
        for name, tag in ADDED.items():self.assertEqual(by_name[name][1],tag)

try:
    TOOLS=bool(importlib.util.find_spec('grpc_tools')) and shutil.which('cc')
except ModuleNotFoundError:
    TOOLS=False

@unittest.skipUnless(TOOLS,'codec tests need grpcio-tools/protobuf and a C compiler')
class SourceCodec(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
        cls.temp=tempfile.TemporaryDirectory(prefix='crt-source-codec-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work=Path(cls.temp.name)
        def message(proto_dir,name):
            descriptor=cls.work/name
            subprocess.run([sys.executable,'-m','grpc_tools.protoc','-I',str(proto_dir),
                            '--descriptor_set_out='+str(descriptor),str(proto_dir/'telemetry.proto')],check=True,capture_output=True)
            data=descriptor_pb2.FileDescriptorSet.FromString(descriptor.read_bytes())
            pool=descriptor_pool.DescriptorPool()
            for file in data.file:pool.Add(file)
            return message_factory.GetMessageClass(pool.FindMessageTypeByName('TelemetryPayload'))
        cls.new_message=message(FILL/'proto','new-descriptor')
        old=cls.work/'old';old.mkdir()
        legacy='\n'.join(line for line in (FILL/'proto/telemetry.proto').read_text().splitlines()
                         if not (re.search(r'=\s*(\d+)\s*;',line) and int(re.search(r'=\s*(\d+)\s*;',line).group(1))>66))+'\n'
        (old/'telemetry.proto').write_text(legacy)
        cls.old_message=message(old,'old-descriptor')
        nanopb=FILL/'vendor/nanopb'
        subprocess.run([sys.executable,str(nanopb/'generator/nanopb_generator.py'),'-I',str(FILL/'proto'),
                        '-D',str(cls.work),str(FILL/'proto/telemetry.proto')],check=True,capture_output=True)
        helper=cls.work/'bridge.c'
        helper.write_text('''#include "telemetry_codec.h"
size_t capacity(void) { return TelemetryPayload_size; }
bool transcode(const uint8_t *input, size_t length, uint8_t *output, size_t cap, size_t *written) {
    TelemetryPayload frame = TelemetryPayload_init_zero;
    if (!telemetry_decode(input, length, &frame)) return false;
    return telemetry_encode(&frame, output, cap, written);
}
''')
        library=cls.work/'codec.so'
        subprocess.run(['cc','-shared','-fPIC','-I'+str(nanopb),'-I'+str(cls.work),'-I'+str(FILL/'csrc'),
                        str(helper),str(FILL/'csrc/telemetry_codec.c'),str(cls.work/'telemetry.pb.c'),
                        *[str(nanopb/name) for name in ('pb_common.c','pb_encode.c','pb_decode.c')],
                        '-o',str(library)],check=True,capture_output=True)
        cls.codec=ctypes.CDLL(str(library))
        cls.codec.capacity.restype=ctypes.c_size_t
        cls.codec.transcode.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
        cls.codec.transcode.restype=ctypes.c_bool

    def transcode(self,data):
        capacity=self.codec.capacity();output=ctypes.create_string_buffer(capacity);written=ctypes.c_size_t()
        if not self.codec.transcode(data,len(data),output,capacity,ctypes.byref(written)):return None
        self.assertLessEqual(written.value,capacity)
        return output.raw[:written.value]

    def test_new_metadata_survives_actual_nanopb_roundtrip_without_uint64_precision_loss(self):
        source=self.new_message(sync_word=0xdeadbeef,pt_1_pressure=123.5,ms_since_boot_fill=99,
            source_metadata_version=1,publisher_session_hi=2**64-1,publisher_session_lo=2**53+1,
            publisher_sequence=2**64-1,source_monotonic_ms=1500,source_unix_ms=1_800_000_000_123,
            source_unix_valid=True,source_time_quality=1,source_time_generation=2,
            adc1_sample_age_ms=0,adc1_sample_age_valid=True,adc2_sample_age_ms=1200,
            adc2_sample_age_valid=True,fsw_receive_age_ms=0,fsw_receive_age_valid=False)
        decoded=self.new_message.FromString(self.transcode(source.SerializeToString()))
        self.assertEqual(decoded,source)

    def test_old_producer_decodes_as_explicit_legacy_not_valid_epoch_zero(self):
        old=self.old_message(sync_word=0xdeadbeef,pt_1_pressure=123.5,ms_since_boot_fill=2**64-1)
        decoded=self.new_message.FromString(self.transcode(old.SerializeToString()))
        self.assertEqual(decoded.pt_1_pressure,123.5)
        self.assertEqual(decoded.ms_since_boot_fill,2**64-1)
        self.assertEqual(decoded.source_metadata_version,0)
        self.assertFalse(decoded.source_unix_valid)
        self.assertFalse(decoded.adc1_sample_age_valid)

    def test_legacy_consumer_can_ignore_new_metadata_without_changing_readings(self):
        frame=self.new_message(pt_1_pressure=123.5,availability_version=1,valid_readings_mask=7,
                               source_metadata_version=1,publisher_session_hi=55,publisher_sequence=20)
        old=self.old_message.FromString(self.transcode(frame.SerializeToString()))
        old.DiscardUnknownFields()
        self.assertEqual(old.pt_1_pressure,123.5)
        self.assertEqual(old.valid_readings_mask,7)

    def test_truncated_protobuf_is_rejected(self):
        self.assertIsNone(self.transcode(b'\xff\xff\xff'))

if __name__ == '__main__':unittest.main()
