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
