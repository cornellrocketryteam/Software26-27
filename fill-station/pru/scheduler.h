#ifndef FILL_PWM_SCHEDULER_H
#define FILL_PWM_SCHEDULER_H
#include <stdint.h>
#define PWM_MAGIC UINT32_C(0x46535057)
#define PWM_VERSION 1u
#define PWM_CHANNELS 20u
#define PWM_TIMEOUT_US 500000u
#define PWM_CONFIG 1u
#define PWM_SET 2u
#define PWM_HEARTBEAT 3u
#define PWM_DISABLE 4u
#define PWM_STATUS 5u
#define PWM_ARM 6u
#define PWM_OK 0u
#define PWM_BAD_MESSAGE 1u
#define PWM_RANGE 2u
#define PWM_NOT_CONFIGURED 3u
#define PWM_TIMEOUT 4u
/* Wire format: exactly 11 little-endian uint32 words. Reply uses period_us as
 * status, pulse_us as current pulse, safe_us as enabled mask, flags as fault mask. */
struct pwm_message {
    uint32_t magic, version, op, seq, bit;
    uint32_t period_us, pulse_us, safe_us, flags, min_us, max_us;
};
struct pwm_channel {
    uint32_t period, pulse, pending, safe, minimum, maximum;
    uint32_t rise, fall;
    uint8_t high;
};
struct pwm_engine {
    struct pwm_channel channels[PWM_CHANNELS];
    uint32_t allowed_mask, configured_mask, enabled_mask, fault_mask;
    uint32_t output, last_contact, next_event;
};
void pwm_init(struct pwm_engine *, uint32_t allowed_mask, uint32_t now);
void pwm_command(struct pwm_engine *, const struct pwm_message *, uint32_t length,
                 uint32_t now, struct pwm_message *reply);
uint32_t pwm_run(struct pwm_engine *, uint32_t now);
/* Force disabled outputs after a timing fault. Reconfiguration is required. */
void pwm_timing_fault(struct pwm_engine *);
#endif
