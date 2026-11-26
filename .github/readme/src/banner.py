# The README art (banners, header strips, screenshot boards), drawn in the house style: flat colours, one dark
# outline, Grandstander and Lexend. Run from this folder with Node (Playwright) and Python 3, for example:
#   python3 banner.py '{"out":"../banner.png","kicker":"monstertenmath.com","title2":"","sub":"…","pills":["…"]}'
# Then shrink: quantize the PNG to ~200 colours (Pillow) before committing.
import sys, json, subprocess
defs = open('defs.svgfrag').read()
FONT = '<link href="https://fonts.googleapis.com/css2?family=Grandstander:wght@900&family=Lexend:wght@400;600&display=swap" rel="stylesheet">'
def banner(out, kicker, title2, sub, pills):
    pill_html = ''.join(f'<span class="pill">{p}</span>' for p in pills)
    html = f'''<!doctype html><html><head><meta charset="utf-8">{FONT}<style>
html,body{{margin:0}} body{{width:1280px;height:400px;background:#22306A;position:relative;overflow:hidden;font-family:Lexend,sans-serif}}
.mark{{position:absolute;left:70px;top:38px}}
.txt{{position:absolute;left:420px;top:62px;right:60px}}
.kick{{display:inline-block;background:#FFC233;color:#2B2420;border:3px solid #2B2420;border-radius:999px;padding:4px 16px;font-weight:600;font-size:20px;box-shadow:4px 4px 0 #2B2420}}
h1{{font-family:Grandstander;font-weight:900;font-size:96px;line-height:1;margin:18px 0 8px;color:#fff;text-shadow:5px 5px 0 #2B2420;letter-spacing:-1px}}
h1 b{{color:#FFC233;font-weight:900}} h1 i{{font-style:normal;color:#fff;font-size:56px;margin-left:14px;letter-spacing:0}}
.k2{{background:#13A08C;color:#fff;margin-left:12px}}
.sub{{color:#FFFCF7;font-size:27px;margin:0 0 22px}}
.pill{{display:inline-block;background:#FFFCF7;color:#2B2420;border:3px solid #2B2420;border-radius:12px;padding:5px 14px;font-weight:600;font-size:18px;margin-right:10px;box-shadow:4px 4px 0 #13A08C}}
svg.c{{position:absolute}}
</style></head><body>
<svg class="c" style="left:1170px;top:30px" width="60" height="60" viewBox="0 0 60 60"><path d="M30 4 L37 22 L56 23 L41 35 L46 54 L30 43 L14 54 L19 35 L4 23 L23 22Z" fill="#FFC233" stroke="#2B2420" stroke-width="3.5" stroke-linejoin="round"/></svg>
<svg class="c" style="left:1200px;top:300px" width="46" height="46" viewBox="0 0 46 46"><path d="M23 5 L42 40 L4 40Z" fill="#F2542D" stroke="#2B2420" stroke-width="3.5" stroke-linejoin="round"/></svg>
<svg class="c" style="left:1010px;top:52px" width="34" height="34" viewBox="0 0 34 34"><circle cx="17" cy="17" r="13" fill="#fff" stroke="#2B2420" stroke-width="3.5"/></svg>
<svg class="c" style="left:1196px;top:200px" width="26" height="26" viewBox="0 0 26 26"><rect x="3" y="3" width="20" height="20" rx="4" fill="#13A08C" stroke="#2B2420" stroke-width="3" transform="rotate(14 13 13)"/></svg>
<svg class="mark" width="320" height="330" viewBox="0 0 150 166" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">{defs}<use xlink:href="#mark1"/></svg>
<div class="txt"><span class="kick">{kicker}</span>{f'<span class="kick k2">{title2}</span>' if title2 else ''}<h1>Monster <b>Ten</b></h1><p class="sub">{sub}</p>{pill_html}</div>
</body></html>'''
    open(out + '.html', 'w').write(html)
    subprocess.run(['node', 'render.js', out + '.html', out, '1280', '400'], check=True)
cfg = json.loads(sys.argv[1])
banner(**cfg)
