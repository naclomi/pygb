import rlcompleter, readline
import code
import sys
import operator
import traceback

class DEBUGGER_TRIGGER(Exception):
    pass

class DEBUGGER(object):
    def __init__(self, system, verbose=False):
        self.system = system
        self.verbose = verbose # TODO: expose through debug_locals
        self.breakpoints = {}

        def manual_trigger():
            val = self.system.debug_trigger 
            self.system.debug_trigger = False
            return val
        self.breakpoints["manual"] = manual_trigger

        def new(trigger):
            name = "B%d" % len(self.breakpoints)
            self.breakpoints[name] = trigger
            print "Added breakpoint " + name

        def step():
            self.system.debug_trigger = True
            sys.exit(0xBADBEEF) # :B

        self.debug_locals = {}
        self.debug_locals["breakpoints"] = self.breakpoints
        self.debug_locals["new"] = new
        self.debug_locals["step"] = step
        self.debug_locals.update(self.system.__dict__)

        # TODO: the scope for tab completions isn't right
        readline.parse_and_bind("tab: complete")

    def scan(self):
        triggered = []

        for break_name, breakpoint in self.breakpoints.items():
            try:
                if breakpoint():
                    triggered.append(break_name)
            except:
                print "WARNING: Breakpoint %s failed with exception:" % break_name
                traceback.print_exc()
                triggered.append("%s (EXCEPTION)" % break_name)
        if len(triggered) > 0:
            print "BREAKPOINTS TRIGGERED: " + ", ".join(triggered)
            self.start()
        elif self.verbose:
            # TODO: core dump is showing 'next pc' and 'current regs'
            print self.system.cpu.core_dump()
            print "frame %d" % self.system.video_driver.frame
            print "------------"


    def start(self):
        print "------------"
        print "CORE DUMP"
        print self.system.cpu.core_dump()
        print "------------"
        try:
            code.interact(local=self.debug_locals)
        except SystemExit as e:
            if e.args[0] == 0xBADBEEF:
                pass
            else:
                exit(e.args[0])
