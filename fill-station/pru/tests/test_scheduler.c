#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "scheduler.h"

static struct pwm_message msg(uint32_t op, uint32_t seq, uint32_t bit) {
    struct pwm_message m = {PWM_MAGIC, PWM_VERSION, 0, 0, 0, 20000, 1500, 1000, 1, 500, 2500};
    m.op = op; m.seq = seq; m.bit = bit; return m;
}
static void command(struct pwm_engine *e, struct pwm_message m, uint32_t now) {
    struct pwm_message reply;
    pwm_command(e, &m, sizeof m, now, &reply);
    assert(reply.period_us == PWM_OK);
}
int main(void) {
    struct pwm_engine e;
    struct pwm_message m, r;
    pwm_init(&e, 3, 0);
    assert(pwm_run(&e, 0) == 0);
    command(&e, msg(PWM_CONFIG, 1, 0), 0);
    assert(pwm_run(&e, 0) == 0);
    assert(pwm_run(&e, 500) == 1);
    assert(pwm_run(&e, 1499) == 1);
    assert(pwm_run(&e, 2000) == 0);
    /* A changed pulse only takes effect at the next rising edge. */
    m=msg(PWM_SET, 2, 0); m.pulse_us=2000; command(&e,m,2100);
    assert(pwm_run(&e,20500)==1);
    assert(pwm_run(&e,22499)==1);
    assert(pwm_run(&e,22500)==0);
    /* Independently timed second channel, 500 Hz. */
    m=msg(PWM_CONFIG,3,1); m.period_us=2000; m.pulse_us=500; m.safe_us=500;
    m.min_us=100; m.max_us=1000; command(&e,m,22500);
    assert(pwm_run(&e,23000)==2);
    assert(pwm_run(&e,23500)==0);
    assert(pwm_run(&e,25000)==2);
    /* Invalid packets cannot claim unowned bits or change settings. */
    m=msg(PWM_CONFIG,4,2); pwm_command(&e,&m,sizeof m,25000,&r);
    assert(r.period_us==PWM_RANGE);
    m=msg(PWM_SET,5,0); m.pulse_us=2501; pwm_command(&e,&m,sizeof m,25000,&r);
    assert(r.period_us==PWM_RANGE);
    pwm_command(&e,&m,4,25000,&r); assert(r.period_us==PWM_BAD_MESSAGE);
    /* Timeout selects safe waveform and latches fault until CONFIG. */
    { uint32_t t;
      for(t=25001;t<=525000;t++) pwm_run(&e,t);
    }
    assert(e.fault_mask==3);
    command(&e,msg(PWM_HEARTBEAT,6,0),525000);
    m=msg(PWM_SET,7,0); pwm_command(&e,&m,sizeof m,525000,&r);
    assert(r.period_us==PWM_TIMEOUT);
    command(&e,msg(PWM_CONFIG,8,0),525000);
    assert((e.fault_mask&1)==0);
    /* Stage all channels disabled, then arm together after host initialization. */
    pwm_init(&e,3,0);
    m=msg(PWM_CONFIG,1,0); m.flags=0; command(&e,m,0);
    m=msg(PWM_CONFIG,2,1); m.flags=0; command(&e,m,0);
    assert(pwm_run(&e,0)==0);
    command(&e,msg(6,3,0),100);
    assert(pwm_run(&e,110)==0);
    assert(pwm_run(&e,600)==3);
    m=msg(PWM_ARM,4,0); pwm_command(&e,&m,sizeof m,601,&r);
    assert(r.period_us!=PWM_OK);
    /* A missed edge faults low, never silently stretches an actuator pulse. */
    pwm_init(&e,1,0); command(&e,msg(PWM_CONFIG,1,0),0);
    assert(pwm_run(&e,500)==1);
    assert(pwm_run(&e,2003)==0); assert(e.fault_mask==1);
    /* Deadline arithmetic must work across the 32-bit microsecond wrap. */
    pwm_init(&e,1,UINT32_MAX-1000);
    command(&e,msg(PWM_CONFIG,1,0),UINT32_MAX-1000);
    assert(pwm_run(&e,UINT32_MAX-500)==1);
    assert(pwm_run(&e,999)==0);
    assert(pwm_run(&e,19499)==1);
    puts("PRU scheduler tests passed");
}
