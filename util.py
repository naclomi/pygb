def time_str(time):
    time = float(time)
    if time >= 1:
        return "%.1fs" % time
    elif 1e-3 <= time < 1:
        return "%.1fms" % (time/1e-3)
    elif 1e-6 <= time < 1e-3:
        return "%.1fus" % (time/1e-6)
    else:
        return "%.1fns" % (time/1e-9)

def objdumper(obj):
    def get_elem_str(elem):
        should_print = True
        if type(elem) is int:
            elem_str = "%d (0x%04X)" % (elem, elem)
        elif type(elem) is list or type(elem) is tuple:
            elem_str = []
            for subelem in elem:
                subelem_str, sub_should_print = get_elem_str(subelem)
                if not sub_should_print:
                    should_print = False
                    break
                elem_str.append(subelem_str)
            elem_str = ", ".join(elem_str)
            elem_str = "[" + elem_str + "]"
            if len(elem_str) > 256:
                elem_str = "[...%d elems...]" % len(elem)
        else:
            elem_str = str(elem)
            should_print = not (elem_str[0] == "<") and "\n" not in elem_str
        return elem_str, should_print

    selfstr = []
    elem_name_len = max([len(name) for name in obj.__dict__.keys()])
    for elem_name, elem in obj.__dict__.items():
        if not callable(elem):
            elem_str, should_print = get_elem_str(elem)
            if not should_print:
                continue
            selfstr.append("%*s: %s" % (elem_name_len, elem_name, elem_str))
    return "\n".join(selfstr)
