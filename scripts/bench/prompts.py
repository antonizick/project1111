"""Fixed bake-off prompt set: 10 photoreal, 3 3D-avatar, 3 logo. Non-sexual, no real people."""

from __future__ import annotations

PHOTO = {
    "p01": "photo of a misty mountain lake at sunrise, pine forest, mirror reflections, golden light, ultra detailed, 35mm",
    "p02": "photo of a rainy neon city street at night, wet asphalt reflections, cinematic, shallow depth of field",
    "p03": "portrait photo of an elderly fisherman with a weathered face and a knitted cap, harbor background, soft window light, 85mm",
    "p04": "photo of a red vintage sports car parked on a coastal road at golden hour, ocean in the background",
    "p05": "macro photo of a dew-covered green leaf with a small ladybug, bokeh background, natural light",
    "p06": "aerial photo of a winding river through autumn forest, orange and red trees, overcast sky",
    "p07": "photo of a cozy modern living room interior, large windows, plants, warm evening light, architectural photography",
    "p08": "portrait photo of a young woman hiking in a fleece jacket, smiling, mountain trail background, natural daylight",
    "p09": "photo of the milky way over desert rock formations, long exposure, starry night sky",
    "p10": "photo of a steaming cup of coffee on a wooden cafe table, morning sunlight, shallow depth of field",
}
AVATAR = {
    "a01": "3d animated character, bobblehead caricature of a cheerful bearded man in a plaid shirt, big head small body, glossy render, studio lighting, cute",
    "a02": "3d animated character, bobblehead of a smiling woman with curly red hair wearing glasses, big head, soft lighting, cartoon movie style render",
    "a03": "3d animated character, bobblehead of a friendly robot mechanic holding a wrench, big head, vibrant colors, toy-like render",
}
LOGO = {
    "l01": "minimalist flat vector logo of a fox head, orange and white, clean lines, centered on a plain white background",
    "l02": "esports mascot logo of a roaring wolf, bold outlines, blue and silver, emblem style, dark background",
    "l03": "simple geometric logo mark of a mountain and sun, two colors, flat design, centered, white background",
}
ALL = {**PHOTO, **AVATAR, **LOGO}

NEGATIVE = "worst quality, low quality, blurry, deformed, disfigured, watermark, signature, jpeg artifacts"
NEGATIVE_SD15 = (
    "deformed iris, deformed pupils, worst quality, low quality, jpeg artifacts, ugly, duplicate, "
    "mutilated, extra fingers, mutated hands, blurry, watermark, text"
)
SEEDS = [1111, 424242, 9001]
