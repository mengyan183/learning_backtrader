# -*- coding: utf-8 -*-
"""生成贪恐指数讲解视频的画面卡片（1080×1920，深色主题，与 dashboard 同风格）。

用法: .venv/bin/python scripts/make_explain_cards.py
输出: docs/media/card_1.png ... card_6.png
"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
BG_TOP, BG_BOT = (22, 27, 34), (13, 17, 23)
ACCENT = (88, 166, 255)      # #58a6ff
TEXT = (230, 237, 243)       # #e6edf3
MUTED = (139, 148, 158)      # #8b949e
BORDER = (48, 54, 61)

FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

def font(size, index=0):
    return ImageFont.truetype(FONT, size, index=index)

def grad_bg(draw):
    for y in range(H):
        t = y / H
        c = tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=c)

def wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=fnt) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines

def draw_header(draw, idx):
    draw.text((70, 96), "贪恐指数 · 原理讲解", font=font(30), fill=MUTED)
    draw.text((W - 70 - 120, 96), f"{idx:02d} / 06", font=font(30), fill=MUTED)
    draw.line([(70, 160), (W - 70, 160)], fill=BORDER, width=2)

def draw_subtitle(draw, text):
    """底部字幕条：半透明黑底 + 白色换行文字。"""
    lines = wrap(draw, text, font(34), W - 200)
    line_h = 52
    box_h = len(lines) * line_h + 64
    y0 = H - box_h - 60
    draw.rectangle([(60, y0), (W - 60, y0 + box_h)],
                   fill=(0, 0, 0, 200))
    # 半透明：PIL RGBA 需要单独层
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rectangle([(60, y0), (W - 60, y0 + box_h)], fill=(10, 14, 20, 205))
    draw._image.paste(ov, (0, 0), ov)
    for i, ln in enumerate(lines):
        draw.text((110, y0 + 34 + i * line_h), ln, font=font(34), fill=(255, 255, 255))

def draw_big_title(draw, title, sub, cy):
    draw.text((70, cy), title, font=font(64), fill=TEXT)
    draw.text((70, cy + 100), sub, font=font(32), fill=MUTED)

def zone_bar(draw, x, y, w, h, colors, names=None):
    """五档色带。"""
    seg = w / 5
    for i in range(5):
        draw.rectangle([(x + i * seg, y), (x + (i + 1) * seg, y + h)], fill=colors[i])
    if names:
        for i, n in enumerate(names):
            tw = draw.textlength(n, font=font(24))
            draw.text((x + i * seg + (seg - tw) / 2, y + h + 14), n,
                      font=font(24), fill=TEXT)

Z5 = [(139, 0, 0), (217, 83, 79), (240, 173, 78), (92, 184, 92), (0, 100, 0)]
Z5_NAME = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]

CARDS = [
    # 1 开场：温度计
    ("card_1.png", 1, "市场情绪温度计",
     "指数 = 0 ~ 100\n0 = 极度恐慌   100 = 极度贪婪",
     "贪婪恐惧指数，是一个从零到一百的市场情绪温度计。数值越低，市场越恐慌；数值越高，市场越贪婪。"),
    # 2 四因子
    ("card_2.png", 2, "四因子加权合成",
     "权重：VIX 0.30 · 期限 0.20 · 价格 0.30 · 广度 0.20",
     "指数由四个因子加权合成：VIX波动率因子，权重零点三；期限结构因子，权重零点二；价格动量因子，权重零点三；市场广度因子，权重零点二。"),
    # 3 五档
    ("card_3.png", 3, "五档区间",
     "Σw·score / Σw → 0-100",
     "每个因子每天算出一个零到一百的分数，按权重加权平均，就得到当天的指数。指数分五档：零到二十是极度恐惧，二十到四十是恐惧，四十到六十是中性，六十到八十是贪婪，八十到一百是极度贪婪。"),
    # 4 守猪待兔
    ("card_4.png", 4, "守猪待兔口径",
     "原始标尺 -100 ~ 100\n恐慌 ≤ -60   |   贪婪 ≥ +60",
     "系统同时参考守猪待兔系数。守猪待兔的官方原始口径是负一百到正一百：恐慌小于等于负六十，贪婪大于等于正六十。"),
    # 5 推荐动作
    ("card_5.png", 5, "推荐动作规则",
     "恐慌→买入   中性→观望   贪婪→卖出",
     "持仓看板会结合这两个系统，给每只标的推荐动作：恐慌时建议买入，中性时建议观望，贪婪时建议卖出。"),
    # 6 每日链
    ("card_6.png", 6, "每日自动运行",
     "05:30 定时任务 → 指数计算 → 飞书简报",
     "指数每天清晨由定时任务自动计算，并通过飞书推送投研简报，包括市场信号、持仓建议和相关新闻。"),
]

def draw_card(path, idx, title, sub, sub_text):
    img = Image.new("RGB", (W, H), BG_BOT)
    draw = ImageDraw.Draw(img, "RGBA")
    grad_bg(draw)
    draw_header(draw, idx)
    draw_big_title(draw, title, sub.replace("\n", "   "), 260)
    cy = 460
    if idx == 1:
        # 温度计色带 + 指针
        zone_bar(draw, 90, cy, W - 180, 90, Z5, Z5_NAME)
        px = 90 + int((W - 180) * 0.55)
        draw.polygon([(px, cy - 30), (px - 26, cy - 8), (px + 26, cy - 8)],
                     fill=ACCENT)
        draw.text((px - 40, cy - 84), "55 中性", font=font(36), fill=ACCENT)
        draw.text((90, cy + 170), "数值越低越恐慌 · 数值越高越贪婪",
                  font=font(34), fill=TEXT)
    elif idx == 2:
        bars = [("VIX 波动率", 0.30, (88, 166, 255)),
                ("期限结构", 0.20, (210, 153, 34)),
                ("价格动量", 0.30, (126, 231, 135)),
                ("市场广度", 0.20, (248, 81, 73))]
        for i, (n, w, c) in enumerate(bars):
            y = cy + i * 150
            draw.text((90, y), n, font=font(40), fill=TEXT)
            bw = int((W - 300) * w / 0.30)
            draw.rounded_rectangle([(420, y + 8), (420 + bw, y + 62)],
                                   radius=10, fill=c)
            draw.text((420 + bw + 22, y + 10), f"{w:.2f}", font=font(40), fill=c)
    elif idx == 3:
        zone_bar(draw, 90, cy, W - 180, 110, Z5, Z5_NAME)
        draw.text((90, cy + 190), "公式：fg_index = Σ(w×score) / Σw",
                  font=font(36), fill=TEXT)
        draw.text((90, cy + 250), "缺失因子按剩余权重重新归一化",
                  font=font(30), fill=MUTED)
    elif idx == 4:
        # 守猪待兔标尺
        x0, x1 = 90, W - 90
        draw.line([(x0, cy), (x1, cy)], fill=(120, 130, 140), width=6)
        for v, lbl in [(-100, "-100"), (-60, "-60"), (0, "0"), (60, "60"), (100, "100")]:
            px = x0 + (x1 - x0) * (v + 100) / 200
            draw.line([(px, cy - 18), (px, cy + 18)], fill=TEXT, width=4)
            draw.text((px - 30, cy + 34), lbl, font=font(34), fill=TEXT)
        # 恐慌/贪婪区标记
        fpx = x0 + (x1 - x0) * (-60 + 100) / 200
        gpx = x0 + (x1 - x0) * (60 + 100) / 200
        draw.text((x0, cy - 110), "恐慌区", font=font(36), fill=(217, 83, 79))
        draw.text((gpx + 20, cy - 110), "贪婪区", font=font(36), fill=(92, 184, 92))
    elif idx == 5:
        tri = [("恐慌 ≤ -60", "买入", (217, 83, 79)),
               ("中性区间", "观望", (88, 91, 106)),
               ("贪婪 ≥ +60", "卖出", (92, 184, 92))]
        for i, (cond, act, c) in enumerate(tri):
            x = 90 + i * 330
            draw.rounded_rectangle([(x, cy), (x + 280, cy + 330)], radius=22,
                                   outline=c, width=5)
            draw.text((x + 36, cy + 48), cond, font=font(34), fill=TEXT)
            draw.text((x + 36, cy + 130), act, font=font(72), fill=c)
    else:
        nodes = [("05:30 定时任务", ACCENT), ("指数计算", ACCENT), ("飞书投研简报", (63, 185, 80))]
        for i, (n, c) in enumerate(nodes):
            x = 90 + i * 340
            draw.rounded_rectangle([(x, cy), (x + 250, cy + 140)], radius=22,
                                   fill=(22, 27, 34), outline=c, width=4)
            draw.text((x + 28, cy + 48), n, font=font(36), fill=TEXT)
            if i < 2:
                ax = x + 250 + 30
                draw.line([(ax, cy + 70), (ax + 42, cy + 70)], fill=MUTED, width=4)
                draw.polygon([(ax + 52, cy + 70), (ax + 36, cy + 56), (ax + 36, cy + 84)],
                             fill=MUTED)
        draw.text((90, cy + 210), "异常才推送 · 只在每日链抓取守猪待兔 API",
                  font=font(30), fill=MUTED)
    draw_subtitle(draw, sub_text)
    img.save(path)
    print("生成", path)

def main():
    os.makedirs("docs/media", exist_ok=True)
    for fname, idx, title, sub, sub_text in CARDS:
        draw_card(os.path.join("docs/media", fname), idx, title, sub, sub_text)

if __name__ == "__main__":
    main()
