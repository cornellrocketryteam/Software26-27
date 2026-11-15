#include "scheduler.h"
#include <string.h>

static int due(uint32_t now, uint32_t deadline) { return (int32_t)(now-deadline)>=0; }
static void next(struct pwm_engine *e, uint32_t now) {
    uint32_t bit, deadline, delta=PWM_TIMEOUT_US;
    for(bit=0;bit<PWM_CHANNELS;bit++) if(e->enabled_mask&(1u<<bit)) {
        struct pwm_channel *c=&e->channels[bit];
        deadline=c->high && c->pulse<c->period ? c->fall : c->rise;
        if(due(now,deadline)) { delta=0; break; }
        if(deadline-now<delta) delta=deadline-now;
    }
    if(e->enabled_mask && !e->fault_mask && e->last_contact+PWM_TIMEOUT_US-now<delta)
        delta=e->last_contact+PWM_TIMEOUT_US-now;
    e->next_event=now+delta;
}
void pwm_init(struct pwm_engine *e,uint32_t allowed,uint32_t now) {
    memset(e,0,sizeof *e); e->allowed_mask=allowed&0xfffffu;
    e->last_contact=now; e->next_event=now+PWM_TIMEOUT_US;
}
void pwm_timing_fault(struct pwm_engine *e) {
    e->fault_mask |= e->configured_mask;
    e->enabled_mask=0; e->output=0;
}
uint32_t pwm_run(struct pwm_engine *e,uint32_t now) {
    uint32_t bit;
    if(e->enabled_mask && now-e->last_contact>=PWM_TIMEOUT_US) {
        for(bit=0;bit<PWM_CHANNELS;bit++) if(e->enabled_mask&(1u<<bit)) {
            struct pwm_channel *c=&e->channels[bit];
            c->pending=c->safe;
        }
        e->fault_mask |= e->enabled_mask;
    }
    if(!due(now,e->next_event)) return e->output;
    for(bit=0;bit<PWM_CHANNELS;bit++) if(e->enabled_mask&(1u<<bit)) {
        struct pwm_channel *c=&e->channels[bit]; uint32_t mask=1u<<bit;
        if(c->high && c->pulse<c->period && due(now,c->fall)) {
            if(now-c->fall>2) { pwm_timing_fault(e); return 0; }
            e->output &= ~mask; c->high=0;
        }
        if(due(now,c->rise)) {
            uint32_t edge=c->rise;
            if(now-edge>2) { pwm_timing_fault(e); return 0; }
            c->rise=edge+c->period;
            c->pulse=c->pending;
            c->high=c->pulse!=0;
            c->fall=edge+c->pulse;
            if(c->high) e->output|=mask; else e->output&=~mask;
        }
    }
    next(e,now); return e->output;
}
void pwm_command(struct pwm_engine *e,const struct pwm_message *m,uint32_t len,
                 uint32_t now,struct pwm_message *r) {
    uint32_t status=PWM_OK,mask=0; struct pwm_channel *c=0;
    memset(r,0,sizeof *r); r->magic=PWM_MAGIC; r->version=PWM_VERSION;
    if(len==sizeof *m) { r->op=m->op|0x80000000u; r->seq=m->seq; r->bit=m->bit; }
    if(len!=sizeof *m || m->magic!=PWM_MAGIC || m->version!=PWM_VERSION ||
       m->op<PWM_CONFIG || m->op>PWM_ARM) status=PWM_BAD_MESSAGE;
    else if(m->op!=PWM_HEARTBEAT && m->op!=PWM_STATUS && m->op!=PWM_ARM &&
            (m->bit>=PWM_CHANNELS || !(e->allowed_mask&(1u<<m->bit)))) status=PWM_RANGE;
    else {
        if(m->bit<PWM_CHANNELS) { mask=1u<<m->bit; c=&e->channels[m->bit]; }
        if(m->op==PWM_CONFIG) {
            if(m->period_us<2000 || m->period_us>50000 || m->flags>1 ||
               m->min_us<100 || m->min_us>=m->max_us || m->max_us>m->period_us-100 ||
               m->pulse_us<m->min_us || m->pulse_us>m->max_us ||
               m->safe_us<m->min_us || m->safe_us>m->max_us) status=PWM_RANGE;
            else {
                c->period=m->period_us; c->pending=m->pulse_us; c->safe=m->safe_us;
                c->minimum=m->min_us; c->maximum=m->max_us;
                /* Reconfiguration starts low and begins the new cycle locally. */
                c->high=0; c->rise=now+500; c->fall=now; c->pulse=0;
                e->output&=~mask; e->configured_mask|=mask; e->fault_mask&=~mask;
                if(m->flags) e->enabled_mask|=mask; else e->enabled_mask&=~mask;
            }
        } else if(m->op==PWM_SET) {
            if(!(e->configured_mask&mask)) status=PWM_NOT_CONFIGURED;
            else if(e->fault_mask&mask) status=PWM_TIMEOUT;
            else if(m->pulse_us<c->minimum || m->pulse_us>c->maximum) status=PWM_RANGE;
            else c->pending=m->pulse_us;
        } else if(m->op==PWM_ARM) {
            if(e->fault_mask || e->enabled_mask) status=PWM_TIMEOUT;
            else {
                uint32_t b;
                e->enabled_mask=e->configured_mask;
                for(b=0;b<PWM_CHANNELS;b++) if(e->configured_mask&(1u<<b)) {
                    e->channels[b].rise=now+500; e->channels[b].high=0;
                }
            }
        } else if(m->op==PWM_DISABLE) {
            e->enabled_mask&=~mask; e->output&=~mask; c->high=0;
        }
        if(status==PWM_OK && m->op!=PWM_STATUS) e->last_contact=now;
    }
    r->period_us=status;
    r->pulse_us=c?c->pulse:0;
    r->safe_us=e->enabled_mask; r->flags=e->fault_mask;
    next(e,now);
}
