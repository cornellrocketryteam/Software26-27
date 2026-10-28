# Flight-computer simulator for testing the fill station's umbilical (temporary test tool).
#   cmake -S . -B build && cmake --build build -j
#   then copy build/fsw_sim.uf2 to the Pico 2 in BOOTSEL mode
cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico2 CACHE STRING "Board type")
include(pico_sdk_import.cmake)

project(fsw_sim C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

add_executable(fsw_sim main.c)

target_link_libraries(fsw_sim pico_stdlib)
# -Wformat checks the 54-field $TELEM printf against its arguments
target_compile_options(fsw_sim PRIVATE -Wall -Wformat=2)

# Same USB identity as the real FSW (embassy-usb Config::new(0xc0de, 0xcafe))
target_compile_definitions(fsw_sim PRIVATE
    USBD_VID=0xC0DE
    USBD_PID=0xCAFE
    USBD_MANUFACTURER="CRT"
    USBD_PRODUCT="FSW Simulator"
)

pico_enable_stdio_usb(fsw_sim 1)
pico_enable_stdio_uart(fsw_sim 0)
pico_add_extra_outputs(fsw_sim)
