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

; Joypad test

LD HL, $FF00
joy_loop:
LD (HL), $18 ; Enable button readout
NOP
LD A, (HL) ; Sample buttons
BIT 3, A ; Is START pressed?
JP Z, exit
JP joy_loop

exit:
STOP


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