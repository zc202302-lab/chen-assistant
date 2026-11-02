"""DPI-aware checkmark indicators; keep ttk's native input and focus behavior."""
import base64
import math
import struct
import zlib
import tkinter as tk


def _indicator_png(scale, selected=False, disabled=False, active=False):
    """Render rounded boxes and check strokes without platform fonts or assets."""
    width, height = round(28 * scale), round(22 * scale)
    blue = '#1D4ED8' if active else '#2563EB'
    fill = '#CBD5E1' if disabled and selected else blue if selected else '#FFFFFF'
    border = '#D6DDE8' if disabled else blue if active or selected else '#A8B5C8'
    tick = '#F8FAFC' if disabled else '#FFFFFF'
    rgb = lambda color: tuple(bytes.fromhex(color[1:]))
    fill, border, tick = map(rgb, (fill, border, tick))

    def inside(x, y, x1, y1, x2, y2, radius):
        cx, cy = min(max(x, x1 + radius), x2 - radius), min(max(y, y1 + radius), y2 - radius)
        return (x-cx)**2 + (y-cy)**2 <= radius**2

    def stroke(x, y, a, b):
        dx, dy = b[0]-a[0], b[1]-a[1]
        t = min(1, max(0, ((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
        return math.hypot(x-a[0]-t*dx, y-a[1]-t*dy) <= 1.15

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # PNG no-filter scanline.
        for x in range(width):
            samples = []
            for sy in range(3):
                for sx in range(3):
                    px, py = (x+(sx+.5)/3)/scale, (y+(sy+.5)/3)/scale
                    if not inside(px, py, 1, 2, 19, 20, 4):
                        continue
                    color = fill if inside(px, py, 2.3, 3.3, 17.7, 18.7, 2.7) else border
                    if selected and (stroke(px, py, (5.2, 10.8), (8.8, 14.3)) or
                                     stroke(px, py, (8.8, 14.3), (14.8, 7.7))):
                        color = tick
                    samples.append(color)
            raw.extend((*[round(sum(c[i] for c in samples)/len(samples)) if samples else 0
                          for i in range(3)], round(255*len(samples)/9)))
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind+data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def install_checkbutton_style(root, style):
    scale = max(1, float(root.tk.call('tk', 'scaling')) / (96/72))
    images = [tk.PhotoImage(master=root, data=base64.b64encode(_indicator_png(scale, *state)))
              for state in [(False, False, False), (True, False, False), (False, True, False),
                            (True, True, False), (False, False, True), (True, False, True)]]
    root._checkbutton_images = images  # Tcl images must live as long as their widgets.
    element = 'Chen.Checkbutton.indicator'
    if element not in style.element_names():
        style.element_create(element, 'image', images[0],
            ('disabled', 'selected', images[3]), ('disabled', images[2]),
            ('active', 'selected', images[5]), ('selected', images[1]), ('active', images[4]))
    style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        (element, {'side': 'left', 'sticky': ''}),
        ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
            ('Checkbutton.label', {'sticky': 'nswe'})]})]})])
    style.configure('TCheckbutton', background='#F4F6FA', foreground='#18243B',
                    font=('Microsoft YaHei UI', 10), padding=(0, 4))
    style.map('TCheckbutton', background=[('active', '#F4F6FA')],
              foreground=[('disabled', '#94A3B8')])
    style.configure('Reminder.TCheckbutton', background='#FFFFFF')
    style.map('Reminder.TCheckbutton', background=[('active', '#FFFFFF')])
    style.configure('Reminder.TFrame', background='#FFFFFF')
    style.configure('Reminder.TLabel', background='#FFFFFF', foreground='#18243B')
    style.configure('Reminder.TLabelframe', background='#FFFFFF', bordercolor='#E2E8F0',
                    lightcolor='#E2E8F0', darkcolor='#E2E8F0', relief='solid', borderwidth=1)
    style.configure('Reminder.TLabelframe.Label', background='#FFFFFF', foreground='#18243B',
                    font=('Microsoft YaHei UI', 10, 'bold'))
