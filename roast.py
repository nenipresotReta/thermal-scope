"""Coffee recording metrics and a conservative, sample-rate-independent DROP heuristic.

Independent implementation: sudden sustained cooling, not a roast endpoint target.
Artisan behavior reference: https://github.com/artisan-roaster-scope/artisan/blob/master/src/artisanlib/canvas.py
"""
import math
from statistics import median


def metrics(run, now):
    finish = run.get('drop_t') or run.get('end') or now
    fc = run.get('fc_start')
    duration = max(0, finish-run['start'])
    development = max(0, finish-fc) if run.get('mode', 'coffee') == 'coffee' and fc is not None and fc <= finish else None
    green, roasted = run.get('green_weight_g'), run.get('roasted_weight_g')
    loss = green-roasted if green is not None and roasted is not None else None
    return {'development_s': development,
            'development_pct': 100*development/duration if development is not None and duration > 0 else None,
            'weight_loss_g': loss, 'weight_loss_pct': 100*loss/green if loss is not None and green > 0 else None}


def weights(green, roasted):
    if green is None and roasted is None:
        return None, None
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 < v <= 10000000 for v in (green, roasted)):
        raise ValueError('Enter both weights in grams, greater than zero.')
    if roasted > green:
        raise ValueError('Roasted weight cannot exceed green weight.')
    return float(green), float(roasted)


def detect_drop(rows, started):
    """Return a backdated DROP only after >=7 min and a hot, sustained break.

    Use half-second median raw readings so the firmware's 10 s fit/overshoot does
    not move the event. Require >=3 C fall and <=-0.8 C/s over >=2 s, with
    consistently falling bins. Any >1 s acquisition gap clears continuity.
    """
    if not rows or rows[-1]['t']-started < 420:
        return None
    now = rows[-1]['t']
    tail = []
    for row in reversed(rows):
        if row['t'] < max(started, now-12):
            break
        if tail and tail[-1]['t']-row['t'] > 1:
            break
        if not all(math.isfinite(row.get(k, float('nan'))) for k in ('raw', 'temperature', 't')):
            break
        tail.append(row)
    tail.reverse()
    if len(tail) < 8 or tail[-1]['t']-tail[0]['t'] < 5:
        return None
    groups = {}
    for row in tail:
        groups.setdefault(int(row['t']*2), []).append(row)
    bins = [{'t': median(r['t'] for r in group), 'raw': median(r['raw'] for r in group),
             'temperature': median(r['temperature'] for r in group)} for key, group in sorted(groups.items()) if key < int(now*2)]
    if len(bins) < 9:
        return None
    last = bins[-1]
    before = [r for r in bins if last['t']-r['t'] >= 2]
    if not before:
        return None
    baseline = before[-1]
    recent = [r for r in bins if r['t'] >= baseline['t']]
    if len(recent) < 4 or any(b['t']-a['t'] > 1 for a, b in zip(recent, recent[1:])):
        return None
    peak = max(before, key=lambda r: (r['raw'],r['t']))
    fall = baseline['raw']-last['raw']
    slope = (last['raw']-baseline['raw'])/(last['t']-baseline['t'])
    falling = sum(b['raw'] < a['raw']-.02 for a, b in zip(recent, recent[1:]))
    if peak['raw'] < 160 or peak['raw']-last['raw'] < 3 or fall < 2 or slope > -.8 or falling < .75*(len(recent)-1):
        return None
    # Reject old cooldown tails: require a stable/rising lead-in to the break.
    lead = [r for r in bins if peak['t']-3 <= r['t'] < peak['t']]
    if len(lead) < 3 or peak['raw'] < lead[0]['raw']-.5:
        return None
    return {'t': peak['t'], 'temperature': peak['temperature'], 'detected_at': now, 'source': 'auto'}


class DropMonitor:
    """Hold candidates for 20 s; reject rebounds/gaps before backdating a mark."""
    def __init__(self):
        self.run_id = None
        self.candidate = None
        self.last_t = None
        self.minimum = None
        self.cooldown_until = 0

    def update(self, rows, run):
        if run is None or run['id'] != self.run_id or run['mode'] != 'coffee' or not run['auto_drop']:
            self.__init__()
            if run is not None:self.run_id = run['id']
        if run is None or run['mode'] != 'coffee' or not run['auto_drop'] or not rows:
            return None
        row=rows[-1]
        if self.last_t is not None and row['t']-self.last_t > 1:
            self.candidate=None
        self.last_t=row['t']
        if self.candidate is not None:
            self.minimum=min(self.minimum,row['raw'])
            if row['raw'] >= self.candidate['temperature']-2 or row['raw']-self.minimum >= 5:
                self.candidate=None;self.cooldown_until=row['t']+10
            elif row['t']-self.candidate['detected_at'] >= 20 and self.candidate['temperature']-row['raw'] >= 15:
                event={**self.candidate,'detected_at':row['t']}
                self.candidate=None
                return event
        elif row['t'] >= self.cooldown_until:
            self.candidate=detect_drop(rows,run['start'])
            if self.candidate is not None:self.minimum=row['raw']
        return None

    def status(self, now):
        if self.candidate is None:return None
        return {'t':self.candidate['t'], 'temperature':self.candidate['temperature'],
                'confirm_in_s':max(0,20-(now-self.candidate['detected_at'])), 'confirm_at':self.candidate['detected_at']+20}
