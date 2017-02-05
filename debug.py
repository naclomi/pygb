import rlcompleter, readline
import code
import sys
import operator
import imp
import traceback
import os

class Tee(object):
    def __init__(self, name, mode):
        self.file = open(name, mode)
        self.stdout = sys.stdout
        sys.stdout = self
    def __del__(self):
        sys.stdout = self.stdout
        self.file.close()
    def write(self, data):
        self.file.write(data)
        self.stdout.write(data)

class DEBUGGER_TRIGGER(Exception):
    pass

class DEBUGGER(object):
    def __init__(self, system, verbose=False):
        self.system = system
        self.breakpoints = {}

        def manual_trigger():
            val = self.system.debug_trigger 
            self.system.debug_trigger = False
            return val
        self.breakpoints["manual"] = manual_trigger

        def load(filename):
            filename = os.path.expanduser(filename)
            mod_name = os.path.splitext(os.path.basename(filename))[0]
            mod = imp.load_source(mod_name, filename)
            for var, val in self.debug_locals.items():
                setattr(mod, var, val)
            # TODO: fix this import crap?
            globals().update(mod.__dict__)
            return mod

        def watch(fun):
            last_val = [fun()]
            def helper():
                val = fun()
                if last_val[0] != val:
                    last_val[0] = val
                    return True
                else:
                    return False
            return helper

        def instr(addr=None, absolute=False):
            if addr is None:
                addr = self.system.cpu.PC.read()
            elif not absolute:
                addr = self.system.cpu.PC.read() + addr
            return self.system.bus.read(addr)

        def new(trigger):
            name = "B%d" % len(self.breakpoints)
            self.breakpoints[name] = trigger
            print "Added breakpoint " + name

        def step():
            self.system.debug_trigger = True
            sys.exit(0xBADBEEF) # :B

        self.verbose = verbose
        def en_verbose(en=None):
            if en is not None:
                if type(en) is not bool:
                    raise TypeError
                self.verbose = en
            return self.verbose

        self.debug_locals = {}
        self.debug_locals["breakpoints"] = self.breakpoints
        self.debug_locals["watch"] = watch
        self.debug_locals["new"] = new
        self.debug_locals["instr"] = instr
        self.debug_locals["step"] = step
        self.debug_locals["verbose"] = en_verbose
        self.debug_locals["load"] = load
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
            # TODO: reenable:
            #print "frame %d" % self.system.video_driver.frame
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
