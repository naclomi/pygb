.MEMORYMAP
SLOTSIZE $4000
DEFAULTSLOT 1
SLOT 0 $0000
SLOT 1 $4000
.ENDME

.ROMBANKSIZE $4000
.ROMBANKS 2

.RAMSIZE 0
.EMPTYFILL $DD
.CARTRIDGETYPE 1
.COMPUTECHECKSUM
.COMPUTECOMPLEMENTCHECK

;***********************************

.BANK 0 SLOT 0
.ORG $100
NOP
JP $150

.ORG $150

; SCX/SCY test

joy_loop:
LD HL, $FF00
LD (HL), $10 ; Enable button readout
LD D, (HL) ; Sample buttons
BIT 3, D ; START
JP Z, exit
BIT 0, D ; A
CALL Z, flip_colors
NOP
LD HL, $FF00
LD (HL), $20 ; Enable DPAD readout
LD D, (HL) ; Sample dpad
BIT 0, D ; Right
CALL Z, inc_scx
BIT 1, D ; Left
CALL Z, dec_scx
BIT 2, D ; Up
CALL Z, dec_scy
BIT 3, D ; Down
CALL Z, inc_scy

JP joy_loop
exit:
STOP

flip_colors:
LD HL, $FF47
LD A, (HL)
LD B, $FF
XOR B
LD (HL), A
RET

inc_scx:
LD HL, $FF43
LD A, (HL)
INC A
LD (HL), A
RET

dec_scx:
LD HL, $FF43
LD A, (HL)
DEC A
LD (HL), A
RET

inc_scy:
LD HL, $FF42
LD A, (HL)
INC A
LD (HL), A
RET

dec_scy:
LD HL, $FF42
LD A, (HL)
DEC A
LD (HL), A
RET








EI
LD HL, $FF04
LD (HL), 0 
LD HL, $FF07
LD (HL), 4
wait_loop: 
NOP
JP wait_loop

; DIV test
LD HL, $FF04
LD (HL), 0 
time_loop: 
LD A, (HL)
SUB 5
JR NZ, time_loop
STOP

; Basic test
LD B, 254
INC B
INC B
LD B, 4
INC B
INC B
LD A, B
DEC A
JR NZ, -1
LD A, B
loop: DEC A
JP NZ, loop

STOP