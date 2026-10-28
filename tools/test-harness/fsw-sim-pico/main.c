/*
 * Flight-computer (FSW) simulator for the fill station's umbilical.
 * Temporary test tool: plug the Pico 2 into the SK-AM64B's USB host port and it
 * shows up as /dev/ttyACM0, like the real FSW.
 *
 * Speaks the protocol in UMBILICAL_REFERENCE.md:
 *   - emits `$TELEM,<54 fields>\n` at 20 Hz (FSW main loop rate)
 *   - accepts `<...>` commands (<H>, <S>/<s>, <M>/<m>, <V>, <L>, <KA>/<KD>,
 *     <1>-<4>, <A1>-<A3>, <D>/<d>, <R>, <W>, <T,...>, ...) and logs each one
 *   - logs when the heartbeat (<H>) is lost for 15 s and when it returns
 *
 * BOOTSEL button: pause/resume $TELEM while USB stays connected, to simulate a
 * hung FSW (fill station should mark the umbilical stale after 3 s and run its
 * umbilical safety action after 15 s). Unplug the cable to test a real disconnect.
 *
 * LED: solid = streaming, fast blink = paused, slow blink = no host connected.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "hardware/structs/ioqspi.h"
#include "hardware/structs/sio.h"
#include "hardware/sync.h"
#include "hardware/watchdog.h"
#include "pico/stdio_usb.h"
#include "pico/stdlib.h"

#define TELEM_PERIOD_MS 50 /* 20 Hz, like MAIN_LOOP_DELAY_MS in fsw/src/constants.rs */
#define HEARTBEAT_TIMEOUT_MS 15000 /* UMBILICAL_TIMEOUT_MS */
#define CMD_MAX 96

static struct {
    unsigned flight_mode; /* 0 Startup .. 6 Fault */
    bool sv_open, mav_open, key_armed;
    unsigned ssa_drogue, ssa_main;
    unsigned cmd_n[4], cmd_a[3];
    float blims_up_lat, blims_up_lon, blims_down_lat, blims_down_lon;
} st;

/* Read the BOOTSEL button (QSPI CS line); from pico-examples picoboard/button. */
static bool __no_inline_not_in_flash_func(bootsel_pressed)(void)
{
    const uint CS_PIN_INDEX = 1;
    uint32_t flags = save_and_disable_interrupts();
    hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                    GPIO_OVERRIDE_LOW << IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_LSB,
                    IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_BITS);
    for (volatile int i = 0; i < 1000; ++i)
        ;
    bool pressed = !(sio_hw->gpio_hi_in & SIO_GPIO_HI_IN_QSPI_CSN_BITS);
    hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                    GPIO_OVERRIDE_NORMAL << IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_LSB,
                    IO_QSPI_GPIO_QSPI_SS_CTRL_OEOVER_BITS);
    restore_interrupts(flags);
    return pressed;
}

static void emit_telemetry(uint32_t ms)
{
    float t = ms / 1000.0f;
    /* Slowly varying values so dashboards visibly update */
    float wobble = sinf(t * 0.5f);
    printf("$TELEM,"
           "%u,%.1f,%.2f,%.2f,"           /* flight_mode, pressure, temp, altitude */
           "%.6f,%.6f,%u,%.1f,"           /* latitude, longitude, num_satellites, gps_time */
           "%.3f,%.3f,%.3f,"              /* mag */
           "%.3f,%.3f,%.3f,"              /* accel */
           "%.3f,%.3f,%.3f,"              /* gyro */
           "%.1f,%.1f,%.1f,"              /* pt3, pt4, rtd */
           "%u,%u,"                       /* sv_open, mav_open */
           "%u,%u,%u,%u,%u,%u,%u,%u,%u,"  /* ssa_drogue, ssa_main, cmd_n1-4, cmd_a1-3 */
           "%.3f,%.1f,"                   /* airbrake_deployment, predicted_apogee */
           "%u,%u,%.3f,%.3f,%.3f,%.3f,%u,%u,%u,%d," /* h_acc..head_mot */
           "%.3f,%d,%.3f,%.3f,%.1f,"      /* blims outputs */
           "%.6f,%.6f,%.6f,%.6f,%.1f,"    /* blims config */
           "%lu\n",                       /* ms_since_boot_cfc */
           st.flight_mode, 101325.0f + 50.0f * wobble, 21.5f + wobble, 2.0f * wobble,
           42.444600f, -76.501900f, 12u, fmodf(45000.0f + t, 86400.0f),
           25.0f, -5.0f, 40.0f,
           0.05f * wobble, -0.03f, 9.81f,
           0.1f * wobble, -0.2f, 0.05f,
           1200.0f + 100.0f * wobble, 1150.0f - 80.0f * wobble, 2048.0f + 10.0f * wobble,
           st.sv_open, st.mav_open,
           st.ssa_drogue, st.ssa_main, st.cmd_n[0], st.cmd_n[1], st.cmd_n[2], st.cmd_n[3],
           st.cmd_a[0], st.cmd_a[1], st.cmd_a[2],
           0.0f, 3048.0f,
           1500u, 2500u, 0.12, -0.08, 0.01, 0.15, 120u, 450000u, 3u, 0,
           0.0f, 0, 0.0f, 0.0f, 0.0f,
           st.blims_up_lat, st.blims_up_lon, st.blims_down_lat, st.blims_down_lon, 225.0f,
           (unsigned long)ms);
}

static void handle_command(const char *cmd, uint32_t *last_heartbeat_ms, bool *heartbeat_lost)
{
    uint32_t now = to_ms_since_boot(get_absolute_time());

    if (strcmp(cmd, "H") == 0) {
        *last_heartbeat_ms = now;
        if (*heartbeat_lost) {
            *heartbeat_lost = false;
            printf("SIM: heartbeat restored\n");
        }
        return; /* every second; don't log */
    }

    if (strcmp(cmd, "S") == 0) {
        st.sv_open = true;
        printf("SIM: SV opened\n");
    } else if (strcmp(cmd, "s") == 0) {
        st.sv_open = false;
        printf("SIM: SV closed\n");
    } else if (strcmp(cmd, "M") == 0) {
        st.mav_open = true;
        printf("SIM: MAV opened\n");
    } else if (strcmp(cmd, "m") == 0) {
        st.mav_open = false;
        printf("SIM: MAV closed\n");
    } else if (strcmp(cmd, "V") == 0) {
        st.sv_open = st.mav_open = false;
        printf("SIM: Safe - MAV and SV closed\n");
    } else if (strcmp(cmd, "L") == 0) {
        st.flight_mode = 2;
        printf("SIM: Launch command - flight mode Ascent\n");
    } else if (strcmp(cmd, "KA") == 0) {
        st.key_armed = true;
        printf("SIM: Key armed\n");
    } else if (strcmp(cmd, "KD") == 0) {
        st.key_armed = false;
        printf("SIM: Key disarmed\n");
    } else if (cmd[0] >= '1' && cmd[0] <= '4' && cmd[1] == '\0') {
        st.cmd_n[cmd[0] - '1'] = 1;
        printf("SIM: Payload N%c triggered\n", cmd[0]);
    } else if (cmd[0] == 'A' && cmd[1] >= '1' && cmd[1] <= '3' && cmd[2] == '\0') {
        st.cmd_a[cmd[1] - '1'] = 1;
        printf("SIM: Payload A%c triggered\n", cmd[1]);
    } else if (strcmp(cmd, "D") == 0) {
        st.ssa_drogue = 1;
        printf("SIM: Drogue triggered\n");
    } else if (strcmp(cmd, "d") == 0) {
        st.ssa_main = 1;
        printf("SIM: Main triggered\n");
    } else if (strcmp(cmd, "W") == 0) {
        printf("SIM: Flash wipe complete\n");
    } else if (strcmp(cmd, "R") == 0 || strcmp(cmd, "X") == 0) {
        printf("SIM: Rebooting\n");
        sleep_ms(100);
        watchdog_reboot(0, 0, 0); /* USB drops and re-enumerates, like the real FSW */
    } else if (cmd[0] == 'T' && cmd[1] == ',') {
        float a, b, c, d;
        if (sscanf(cmd + 2, "%f,%f,%f,%f", &a, &b, &c, &d) == 4) {
            st.blims_up_lat = a, st.blims_up_lon = b, st.blims_down_lat = c, st.blims_down_lon = d;
            printf("SIM: BLiMS target set\n");
        } else {
            printf("SIM: Bad BLiMS target <%s>\n", cmd);
        }
    } else {
        printf("SIM: Unknown command <%s>\n", cmd);
    }
}

int main(void)
{
    stdio_init_all();
    gpio_init(PICO_DEFAULT_LED_PIN);
    gpio_set_dir(PICO_DEFAULT_LED_PIN, GPIO_OUT);

    char cmd[CMD_MAX];
    size_t cmd_len = 0;
    bool in_cmd = false;

    bool paused = false, button_was_down = false;
    bool heartbeat_lost = false;
    uint32_t last_heartbeat_ms = 0;
    uint32_t next_telem_ms = 0;

    while (true) {
        uint32_t now = to_ms_since_boot(get_absolute_time());

        /* Commands: everything between '<' and '>' */
        int c;
        while ((c = getchar_timeout_us(0)) != PICO_ERROR_TIMEOUT) {
            if (c == '<') {
                in_cmd = true;
                cmd_len = 0;
            } else if (in_cmd && c == '>') {
                cmd[cmd_len] = '\0';
                in_cmd = false;
                handle_command(cmd, &last_heartbeat_ms, &heartbeat_lost);
            } else if (in_cmd && cmd_len < CMD_MAX - 1) {
                cmd[cmd_len++] = (char)c;
            }
        }

        /* Heartbeat watchdog (only once the fill station has started sending them) */
        if (last_heartbeat_ms != 0 && !heartbeat_lost && now - last_heartbeat_ms > HEARTBEAT_TIMEOUT_MS) {
            heartbeat_lost = true;
            printf("SIM: heartbeat lost (no <H> for %d s)\n", HEARTBEAT_TIMEOUT_MS / 1000);
        }

        /* BOOTSEL toggles telemetry pause (edge-triggered) */
        bool button_down = bootsel_pressed();
        if (button_down && !button_was_down) {
            paused = !paused;
            printf("SIM: telemetry %s\n", paused ? "PAUSED (simulating hung FSW)" : "resumed");
        }
        button_was_down = button_down;

        if (!paused && (int32_t)(now - next_telem_ms) >= 0) {
            emit_telemetry(now);
            next_telem_ms = now + TELEM_PERIOD_MS;
        }

        /* LED status */
        bool led;
        if (!stdio_usb_connected())
            led = (now / 500) % 2;
        else if (paused)
            led = (now / 100) % 2;
        else
            led = true;
        gpio_put(PICO_DEFAULT_LED_PIN, led);

        sleep_ms(5);
    }
}
