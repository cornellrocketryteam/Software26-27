# PRU_CGT and PSSP are pinned by the Nix firmware package.
CC ?= cc
.PHONY: test all
BUILD ?= build
CFLAGS = -v3 -O2 --endian=little --hardware_mac=on --include_path=$(PRU_CGT)/include --include_path=$(PSSP)/include --include_path=$(PSSP)/include/am64x --include_path=$(PSSP)/examples/am64x/PRU_RPMsg_Echo_Interrupt$(CORE) --define=PRU_CORE=$(CORE) --define=PRU_ALLOWED_MASK=$(MASK)
all:
	mkdir -p $(BUILD)
	$(PRU_CGT)/bin/clpru $(CFLAGS) --obj_directory=$(BUILD) --compile_only main.c scheduler.c
	$(PRU_CGT)/bin/clpru $(CFLAGS) -z --search_path=$(PRU_CGT)/lib --search_path=$(PRU_CGT)/include --stack_size=0x200 --heap_size=0 --reread_libs --warn_sections --output_file=$(BUILD)/fill-station-pru0_$(CORE)-fw --map_file=$(BUILD)/firmware.map $(BUILD)/main.obj $(BUILD)/scheduler.obj $(PSSP)/examples/am64x/PRU_RPMsg_Echo_Interrupt$(CORE)/AM64x_PRU$(CORE)_intc_rscTbl.cmd --library=libc.a --library=$(PSSP)/lib/rpmsg_lib.lib
test:
	$(CC) -std=c99 -O2 -Wall -Wextra -Werror -I. tests/test_scheduler.c scheduler.c -o /tmp/fill-station-pru-scheduler-test
	/tmp/fill-station-pru-scheduler-test
