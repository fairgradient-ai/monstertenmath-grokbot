# Screenshot boards (showcase) and the header strips (strip) for the READMEs. See banner.py for how to run.
import sys, json, subprocess, base64, os
FONT = '<link href="https://fonts.googleapis.com/css2?family=Grandstander:wght@900&family=Lexend:wght@400;600&display=swap" rel="stylesheet">'
defs = open('defs.svgfrag').read()
def uri(p):
    return 'data:image/png;base64,' + base64.b64encode(open(p,'rb').read()).decode()
def showcase(out, items, w, h, fw, bg='#FFFCF7', cap='#2B2420', crop=None):
    cells = ''.join(f'<figure><div class="f" style="width:{fw}px"><img src="{uri(p)}" style="width:{fw}px;{("height:"+str(crop)+"px;object-fit:cover;object-position:top") if crop else ""}"></div><figcaption>{c}</figcaption></figure>' for p,c in items)
    html = f'''<!doctype html><html><head><meta charset="utf-8">{FONT}<style>
html,body{{margin:0}} body{{width:{w}px;height:{h}px;background:{bg};display:flex;align-items:center;justify-content:center;gap:34px;font-family:Lexend,sans-serif}}
figure{{margin:0;display:flex;flex-direction:column;align-items:center}}
.f{{border:4px solid #2B2420;border-radius:26px;overflow:hidden;box-shadow:8px 8px 0 #2B2420;background:#fff;line-height:0}}
figcaption{{margin-top:20px;font-weight:600;font-size:21px;color:{cap};text-align:center;max-width:{fw+20}px}}
</style></head><body>{cells}</body></html>'''
    open(out+'.html','w').write(html)
    subprocess.run(['node','render.js',out+'.html',out,str(w),str(h)],check=True)
def strip(out, title, sub, accent='#FFC233'):
    html = f'''<!doctype html><html><head><meta charset="utf-8">{FONT}<style>
html,body{{margin:0}} body{{width:1280px;height:170px;background:#22306A;position:relative;overflow:hidden;font-family:Lexend,sans-serif}}
.mark{{position:absolute;left:46px;top:8px}}
.t{{position:absolute;left:220px;top:28px;right:40px}}
.k{{color:#FFFCF7;font-weight:600;font-size:19px;letter-spacing:.5px}} .k b{{color:{accent}}}
h1{{font-family:Grandstander;font-weight:900;font-size:56px;margin:2px 0 4px;color:#fff;text-shadow:4px 4px 0 #2B2420;line-height:1.05;white-space:nowrap}}
.s{{color:#FFFCF7;opacity:.92;font-size:21px;white-space:nowrap}}
.bar{{position:absolute;left:0;right:0;bottom:0;height:10px;background:{accent}}}
</style></head><body>
<svg class="mark" width="136" height="146" viewBox="0 0 150 166" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">{defs}<use xlink:href="#mark1"/></svg>
<div class="t"><div class="k">MONSTER <b>TEN</b></div><h1>{title}</h1><div class="s">{sub}</div></div><div class="bar"></div></body></html>'''
    open(out+'.html','w').write(html)
    subprocess.run(['node','render.js',out+'.html',out,'1280','170'],check=True)
cfg=json.loads(sys.argv[2]); globals()[sys.argv[1]](**cfg)
