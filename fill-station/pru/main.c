/* AM64x Linux remoteproc firmware. RPMsg resources/IRQ maps and library come
 * from the pinned TI PRU Software Support Package (BSD-3-Clause). */
#include <stdint.h>
#include <pru_cfg.h>
#include <pru_iep.h>
#include <pru_intc.h>
#include <pru_rpmsg.h>
#include "resource_table.h"
#if PRU_CORE == 0
#include "intc_map_0.h"
#define TIMER CT_IEP0
#define TO_HOST 16
#define FROM_HOST 17
#define HOST_INTERRUPT (1u<<30)
#else
#include "intc_map_1.h"
#define TIMER CT_IEP1
#define TO_HOST 18
#define FROM_HOST 19
#define HOST_INTERRUPT (1u<<31)
#endif
#include "scheduler.h"

volatile register uint32_t __R30;
volatile register uint32_t __R31;
static struct pwm_engine engine;
static uint8_t payload[RPMSG_MESSAGE_SIZE];
static uint32_t ticks_previous, ticks_remainder, clock_us;
/* IEP uses its dedicated 200 MHz OCP clock, independent of PRU core clock.
 * Accumulate differences before division so raw low-word wrap loses no time. */
static uint32_t now_us(void) {
    uint32_t raw=TIMER.count_reg0;
    uint32_t delta=raw-ticks_previous;
    uint32_t elapsed=delta/200u;
    ticks_previous=raw;
    ticks_remainder+=delta%200u;
    if(ticks_remainder>=200u) { elapsed++; ticks_remainder-=200u; }
    clock_us+=elapsed;
    return clock_us;
}
static void drive(void) {
    uint32_t now=now_us(), deadline=engine.next_event, old=engine.output;
    uint32_t value=pwm_run(&engine,now);
    /* The scheduler is host-tested. This second deadline check also catches
     * execution/transport delays on the real PRU, before writing a late edge.
     * It is a fault detector, not a claim of measured +/-2 us performance. */
    if(value!=old && (int32_t)(now_us()-deadline)>2) {
        pwm_timing_fault(&engine); value=0;
    }
    __R30=(__R30&~PRU_ALLOWED_MASK)|(value&PRU_ALLOWED_MASK);
}
void main(void) {
    struct pru_rpmsg_transport transport;
    struct pwm_message reply;
    uint16_t src,dst,len;
    volatile uint8_t *status=&resourceTable.rpmsg_vdev.status;
    __R30 &= ~PRU_ALLOWED_MASK;
    CT_CFG.iepclk_reg_bit.iep_ocp_clk_en=1;
    CT_CFG.iepclk_reg_bit.iep1_slv_en=0;
    TIMER.global_cfg_reg=0;
    TIMER.compen_reg=0;
    TIMER.slow_compen_reg=0;
    TIMER.count_reg0=0;
    TIMER.count_reg1=0;
    TIMER.global_cfg_reg=0x11; /* count enabled, default increment=1 */
    pwm_init(&engine,PRU_ALLOWED_MASK,0);
    CT_INTC.STATUS_CLR_INDEX_REG=FROM_HOST;
    while(!(*status&4)) { /* Linux DRIVER_OK; outputs remain low. */ }
    pru_rpmsg_init(&transport,&resourceTable.rpmsg_vring0,&resourceTable.rpmsg_vring1,TO_HOST,FROM_HOST);
    while(pru_rpmsg_channel(RPMSG_NS_CREATE,&transport,"rpmsg-raw",30+PRU_CORE)!=PRU_RPMSG_SUCCESS) {}
    for(;;) {
        uint32_t now,slack;
        drive();
        now=now_us(); slack=engine.next_event-now;
        /* At most one bounded-size message per slack opportunity. Never drain
         * an unbounded receive loop while waveform generation is armed. */
        if(!engine.enabled_mask || ((int32_t)slack>200)) {
            if(__R31&HOST_INTERRUPT) CT_INTC.STATUS_CLR_INDEX_REG=FROM_HOST;
            if(pru_rpmsg_receive(&transport,&src,&dst,payload,&len)==PRU_RPMSG_SUCCESS) {
                drive();
                pwm_command(&engine,(const struct pwm_message *)payload,len,now_us(),&reply);
                drive();
                pru_rpmsg_send(&transport,dst,src,&reply,sizeof reply);
                drive();
            }
        }
    }
}
