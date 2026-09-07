# -*- coding: utf-8 -*-
"""打标核心逻辑（EVA02 本地模型，无 GUI 依赖，供后端 API 复用）。"""
import csv
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".m4v", ".flv"}
CACHE_FILENAME = ".image_tagger_cache.json"


def is_video(path):
    return Path(path).suffix.lower() in VIDEO_EXTS

REDUNDANT_TAIL = ("照片", "图片", "图像", "画面", "场景", "摄影", "图")
REDUNDANT_HEAD = ("一张", "一只", "一个", "一幅", "小", "大", "幼", "老")
NOISE_TAGS = {"美丽", "漂亮", "好看", "背景", "美女", "图片", "照片",
              "图像", "画面", "好看图片", "高清", "清晰"}
NSFW_WORDS = {"色情", "情色", "性感", "裸露", "露骨", "裸体", "成人",
              "色气", "色欲", "艳照", "露点", "擦边", "nsfw", "nude", "sexy"}
DIFF_THRESHOLD = 12


def app_home() -> Path:
    """可移植根目录：打包成 EXE 后 = 该用户 AppData/ImageTagger（可写、干净）；
    开发时 = core.py 所在目录。"""
    if getattr(sys, "frozen", False):
        import os
        base = Path(os.environ.get("APPDATA") or Path.home()) / "ImageTagger"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return base
    return Path(__file__).resolve().parent


SETTINGS_FILE = app_home() / "settings.json"

# 程序资源根目录（词典等被打包进 _internal）：frozen 用 sys._MEIPASS，开发用本目录
def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


_BASE_DIR = resource_dir()


def normalize_tag(tag: str) -> str:
    return tag.strip().lower()


# ---------- 标签分类（把所有打标标签归入语义大类） ----------
# 英文名用「分词精确匹配」（下划线/连字符切成 token，避免 eye→eyebrow 之类的误命中）；
# 中文名用「子串匹配」，关键词优先取多字词避免歧义。
# 顺序即优先级：先命中先归类。
_EMOTICONS = {
    "^_^", ">_<", ">.<", "o_o", "0_0", "@_@", "+_+", "=_=", "=3=", "._.",
    ":)", "(:", ";)", ";p", ";o", ";3", ":t", ":d", ":p", ":<", ":i", ":x",
    "3:", "c:", "owo", "uwu", ">_o", ">o<", "^^", "\\o/", "orz", "otl",
    "8d", "x_x", "x.x", "q_q", "qq", ">_>", "<_<",
    ":o", ":3", ":>", ":>=", ":q", ":|", ";(", ";d", ";q", ">:(", ">:)",
    "<o>_<o>", "<|>_<|>", "\\m/", "\\n/", "\\||/", "^^^", "|_|", "u_u", "xd",
    ".3.", "o3o", ":(", ":/", ";3", "d:", "\\o/", "orz", "otl", "t-t", "t_t",
    "q_q", "8)", "8(", "x)", "x(", "o)", "o(", "ovo", "ovo", "owo", "umu",
}

# 英文 token 规则（按优先级排列）
TAG_CAT_EN = [
    ("表情", [
        "smile", "smiling", "grin", "grinning", "frown", "frowning", "blush",
        "blushing", "cry", "crying", "tear", "tears", "weeping", "sob", "sobbing",
        "angry", "anger", "mad", "surprised", "shock", "shocked", "sad", "happy",
        "serious", "shout", "shouting", "scream", "screaming", "wink", "winking",
        "expression", "open_mouth", "closed_eyes", "closed_mouth", "tongue_out",
        "pout", "pouting", "grimace", "gritted_teeth", "laughing", "laughter",
        "smug", "sleepy", "drowsy", "scared", "fear", "nervous", "annoyed",
        "disgusted", "confused", "pensive", "lonely", "stoic", "emotionless",
        "glare", "glaring", "scowl", "scowling", "embarrassed", "flustered",
        "ahegao", "crazy", "insane", "maniac", "evil", "grin", "fang", "fangs",
        "teeth", "licking_lips", "biting_lip", "drooling", "panting", "gasping",
        "sigh", "mumbling", "whispering", "yawning", "snoring",
        "expressionless", "trembling", "heavy_breathing", "breath", "akanbe",
        "wavy_mouth", "tearing_up", "bored", "aroused", "blank_stare",
        "passionate", "seductive", "provocative", "lewd", "innocent", "pure",
        "gentle", "kind", "cruel", "sarcastic", "apathetic", "despair",
        "anguish", "agony", "ecstasy", "pleasure", "moaning", "panting",
        "whimpering", "sobbing", "sniffling", "sparkling_eyes",
        "smirk", "jitome", "furrowed_brow", "sideways_glance", "naughty_face",
        "dot_nose", "smug_face", "poker_face", "deadpan", "hollow_eyes",
        "seductive_smile", "toothy_grin", "closed_mouth_smile", "open_smile",
        "grin_and_bear", "disgust", "contempt", "pride", "guilt", "shame",
        "regret", "longing", "yearning", "affection", "love_struck",
        "heart_pupils", "nosebleed", "blush_lines",
        "wince", "doyagao", "torogao", "gesugao", "turn_pale", "drunk",
        "facepalm", "eyelid_pull", "spit_take", "raised_eyebrow", "panicking",
        "dreaming", "imagining", "thinking", "smiley_face", "sideways_mouth",
        "triangle_mouth", "no_mouth", "covered_face", "covered_mouth",
        "extra_mouth", "stitched_mouth", "stitched_face", "mouth_drool",
        "fucked_silly", "staring", "stare", "stared", "gaze", "gazing",
        "smell", "smelling", "sniffing", "sick", "cold", "hot", "pain",
        "hurt", "crying", "sobbing", "tremble", "shaking", "shivering",
        "fearful", "terrified", "horrified", "shocked", "dazed", "stunned",
        "confused", "dumbfounded", "speechless", "mouth_wide_open", "gaping_mouth",
        "tongue", "blep", "mlem", "licking", "drool",
        "expressions", "reaction_face", "grimacing", "wincing", "squinting",
        "twitching", "squirming", "flustered", "flushing", "blushing",
        "mouth_pull", "come_hither", "teasing_face", "pouty",
    ]),
    ("眼睛", [
        "eye", "eyes", "pupil", "pupils", "iris", "heterochromia", "sclera",
        "eyebags", "empty_eyes", "glowing_eyes", "wide_eyed", "half-closed_eyes",
        "half_closed_eyes", "single_eye", "no_eyes", "crossed_eyes", "rolling_eyes",
        "star_eyes", "heart_eyes", "sparkling_eyes", "dilated_pupils",
        "slit_pupils", "tareme", "tsurime", "sanpaku",
        "one_eye", "one_eyed", "monocle_eye", "heterochromia", "pupils",
        "dilated_pupils", "constricted_pupils", "heart-shaped_pupils",
    ]),
    ("配饰", [
        # 发饰/头部饰品（含 hair 前缀，需先于「发型发色」命中）
        "hair_ornament", "hairpin", "hair_pin", "hairclip", "hair_clip",
        "hairband", "hair_band", "hair_flower", "hair_ribbon", "hair_bow",
        "hair_accessory", "hair_scrunchy", "hair_tie", "hair_stick",
        "hair_beads", "side_ponytail_ornament",
        "hat", "cap", "beret", "bonnet", "hood", "headdress", "headwear",
        "headband", "headpiece", "tiara", "crown", "halo", "veil", "visor",
        "helmet", "headphones", "earphones", "earmuffs", "headset", "earpiece",
        "glasses", "sunglasses", "eyeglasses", "goggles", "monocle", "eyepatch",
        "eye_patch", "blindfold", "mask", "gas_mask", "necklace", "choker",
        "collar", "earring", "earrings", "piercing", "nose_ring", "lip_ring",
        "ring", "bracelet", "bangle", "wristband", "armlet", "anklet", "leglet",
        "thighlet", "watch", "wristwatch", "necklace", "pendant", "brooch",
        "corsage", "scarf", "necktie", "tie", "bowtie", "bow_tie", "cravat",
        "ascot", "belt", "suspenders", "glove", "gloves", "mittens", "ribbon",
        "bow", "bandana", "handkerchief", "shawl", "cape", "capelet", "cloak",
        "apron", "armor", "armour", "chainmail", "gauntlet", "pauldron",
        "weapon", "weapons", "sword", "blade", "katana", "dagger", "knife",
        "gun", "rifle", "pistol", "firearm", "spear", "lance", "shield", "staff",
        "wand", "scythe", "axe", "hammer", "mace", "whip", "baton", "grenade",
        "shoe", "shoes", "boot", "boots", "sandal", "slippers", "heels",
        "high_heels", "sneakers", "bag", "backpack", "purse", "handbag",
        "umbrella", "parasol", "cane", "crutch", "wings",
        # 更多饰品 / 化妆品 / 鞋履
        "footwear", "scrunchie", "neckerchief", "armband", "bandolier", "amulet",
        "beads", "bindi", "gemstone", "gem", "jewel", "jewelry", "neckwear",
        "charm", "talisman", "rosary", "medallion", "badge", "pin", "buckle",
        "eyeshadow", "eyeliner", "mascara", "lipstick", "makeup", "cosmetics",
        "nail_polish", "nails", "fingernails", "toenails", "blush_makeup",
        "face_paint", "war_paint", "tattoo", "piercings", "ear_cuffs",
        "ear_studs", "hoop_earrings", "dangling_earrings", "stud", "chain",
        "anklet", "toe_ring", "belly_ring", "navel_jewelry", "hair_beads",
        "hair_cuffs", "hair_rings", "hair_wrap", "bandeau_band", "sweatband",
        "wristlet", "gauntlets", "vambrace", "greaves", "bracer", "gorget",
        "spaulder", "cuirass", "breastplate", "helmet", "coif", "hood",
        "balaclava", "ski_mask", "surgical_mask", "plague_mask", "party_mask",
        "domino_mask", "masquerade", "lorgnette", "pince-nez", "spectacles",
        "sunglass", "shades", "aviators", "reading_glasses", "safety_goggles",
        "welding_mask", "visor", "headlamp", "flashlight", "torch",
        "sandals", "loafers", "mary_janes", "headgear", "eyewear",
        "eyewear_on_head", "semi-rimless_eyewear", "cross", "crucifix", "ankh",
        "symbol", "polearm", "handgun", "sheath", "bayonet", "bomb", "bullet",
        "cannon", "crossbow", "ammunition", "ammo", "jingle_bell", "bell",
        "tassel", "pom_pom", "pom_poms", "hairpin", "hairclip", "barrette",
        "corsage", "boutonniere", "floral_wreath", "flower_crown",
        "heart", "star", "sparkle", "sparkles", "crescent", "spikes", "circlet",
        "epaulettes", "pauldrons", "leash", "ofuda", "beanie", "bespectacled",
        "toenail_polish", "anklet", "armlet", "bracelet", "bangle", "ring",
        "engagement_ring", "wedding_ring", "charm", "locket", "talisman",
        "ear_ornament", "earclip", "ear_tag", "ear_covers", "earbuds",
        "hachimaki", "nejiri_hachimaki", "magatama", "aiguillette", "arm_guards",
        "faulds", "shoulder_plates", "helm", "mitre", "jingasa", "turban",
        "kanzashi", "hairpods", "lanyard", "handcuffs", "shackles", "noose",
        "chains", "chained", "holster", "shoulder_holster", "quiver", "sheathed",
        "revolver", "shotgun", "m4_carbine", "suppressor", "silencer",
        "bolt_action", "rapier", "greatsword", "chainsaw", "sickle", "naginata",
        "trident", "kunai", "tantou", "bokken", "cleaver", "crowbar", "pickaxe",
        "hook", "anchor", "dumbbell", "weights", "pacifier", "whistle",
        "stethoscope", "flip_flops", "crocs", "converse", "roller_skates",
        "inline_skates", "skates", "geta", "zouri", "okobo", "tengu_geta",
        "beanie", "bonnet", "nightcap", "visor", "headset", "necklace",
        "pendant", "earmuffs", "hair_stick", "hair_sticks", "flower_crown",
        "name_tag", "cowbell", "emblem", "medal", "pentagram", "arrow",
        "seashell", "pearl", "silk", "hair_bell", "bells", "chime",
        "vambraces", "uchiwa", "shimenawa", "facepaint", "horseshoe_ornament",
        "wing_ornament", "arm_guards", "chest_strap", "body_harness",
    ]),
    ("发型发色", [
        "hair", "hairstyle", "bangs", "ponytail", "twintail", "twintails",
        "braid", "braids", "pigtail", "pigtails", "ahoge", "sidelocks",
        "cowlick", "tresses", "blonde", "brunette", "hime_cut", "bob_cut",
        "buzz_cut", "undercut", "dreadlocks", "curly_hair", "wavy_hair",
        "straight_hair", "long_hair", "short_hair", "spiked_hair", "flipped_hair",
        "messy_hair", "bald", "shaved", "hair_bun", "braided",
        "afro", "twin_drills", "drill_hair", "double_bun", "one_side_up",
        "two_side_up", "side_up", "blunt_ends", "pompadour", "mohawk", "mullet",
        "sidetail", "side_tail", "hair_down", "hair_up", "hair_over_eye",
        "hair_over_one_eye", "split-color_hair", "gradient_hair",
        "half_updo", "updo", "hair_down", "loose_hair", "side_bun", "topknot",
        "chignon", "beehive", "bouffant", "pageboy", "pixie_cut", "shag",
        "payot", "side_drill", "ringlets", "quad_tails", "inverted_bob",
        "single_sidelock", "hairpods", "wig", "hair_extension", "sidetail",
        "sidelock", "side_locks", "hairbun", "top_bun", "space_buns",
        "drill", "drills", "twin_tails", "twintail", "bun_cover", "hair_bow",
    ]),
    ("身体", [
        "breast", "breasts", "nipple", "nipples", "areola", "pussy", "penis",
        "vagina", "vulva", "anus", "ass", "butt", "buttocks", "thigh", "thighs",
        "belly", "navel", "collarbone",
        "tongue", "lips", "lip", "nude", "naked", "topless", "skin", "muscle",
        "muscles", "abs", "cum", "semen", "ejaculation", "genital", "genitals",
        "pubic", "pubes", "groin", "armpit", "cleavage", "underboob",
        "sideboob", "bust", "tits", "testicles", "balls", "scrotum", "labia",
        "clitoris", "foreskin", "glans", "sweat", "sweating", "saliva", "blood",
        "torso", "midriff", "ribcage", "neck", "mole", "freckles", "tan",
        "tanlines", "muscular", "chubby", "plump", "blush_stickers", "stomach",
        "tentacle", "tentacles", "womb", "uterus", "navel_piercing",
        "back", "biceps", "beard", "facial_hair", "birthmark", "eyelashes",
        "eyebrows", "body_hair", "cameltoe", "pubic_hair", "puffy_nipples",
        "inverted_nipples", "small_breasts", "flat_chest", "large_breasts",
        "huge_breasts", "gigantic_breasts", "breast_grab", "breast_squeeze",
        "protruding", "gap", "thigh_gap", "abs", "six-pack", "six_pack",
        "paunch", "beer_belly", "love_handles", "hourglass", "slim", "thin",
        "skinny", "petite", "curvy", "voluptuous", "busty", "topless",
        "half-naked", "half_naked", "semi-nude", "semi_nude", "stripped",
        "undressed", "undressing", "disrobing", "nudity", "exposed",
        "cleavage_cutout", "underboob", "sideboob", "backboob", "underbust",
        "midriff", "stomach", "tummy", "belly_button", "innie",
        "outie", "dimples_of_venus", "collar_bones", "decolletage",
        "bare_shoulders", "bare_arms", "bare_legs", "bare_chest", "bare_back",
        "bare_feet", "barefoot", "armpits", "sweatdrop", "sweat_drop", "wet",
        "forehead", "pectorals", "large_pectorals", "skindentation", "veins",
        "soles", "facial_mark", "scar", "bruise", "bruises", "bandages",
        "bandage", "bandaid", "bandaged", "erection", "wide_hips", "dimples",
        "barefoot_sandals", "cheeks", "chin", "jawline", "adam's_apple",
        "double_chin", "cleft_chin", "dimpls", "goosebumps", "hickey",
        "love_bite", "kiss_mark", "lipstick_mark", "wound", "injury",
        "bulge", "cumdrip", "cleft_of_venus", "large_areolae", "kneepits",
        "steaming_body", "toned", "stubble", "mustache", "goatee", "sideburns",
        "nose", "fins", "webbed_hands", "webbed_feet", "clawed_hands", "talons",
        "fangs", "tusks", "trunk", "snout", "muzzle", "whiskers", "antenna",
        "carapace", "exoskeleton", "mandibles", "pincers", "stinger",
        "foot_focus", "hand_focus", "presenting_foot", "foot_up", "ankle_grab",
        "dorsiflexion", "toe_scrunch", "heel_up", "leg_lift", "leg_wrap",
        "outstretched_leg", "foot_worship", "perineum", "areolae", "ribs",
        "hip_bones", "shoulder_blades", "nape", "crotch", "crotch_seam",
        "crotch_grab", "crotch_cutout", "crotch_rub", "median_furrow",
        "underbutt", "handprint", "slap_mark", "stitches", "body_markings",
        "whisker_markings", "precum", "pee", "peeing", "snot", "lactation",
        "orgasm", "nakadashi", "ovum", "sperm_cell", "fertilization",
        "pregnancy", "pregnant", "inflation", "fat", "fat_rolls", "fat_mons",
        "hairy", "fewer_digits", "missing_limb", "amputee", "prosthesis",
        "prosthetic_arm", "prosthetic_leg", "disembodied_limb",
        "single_mechanical_arm", "mechanical_parts", "joints", "bone", "spine",
        "double_amputee", "dicknipples", "nipple_fuck", "peeing_self",
        "small_breasts", "puffy_nipples", "erect_nipples", "hard_nipples",
        "cameltoe", "pubic_hair", "genitals", "scrotum", "testicle",
        "semen", "ejaculate", "pre-ejaculate", "clitoris", "labia_majora",
        "labia_minora", "areola", "breast", "breasts", "cleavage", "underboob",
        "sideboob", "ass", "buttocks", "thighs", "thigh", "waist", "belly",
        "belly_button", "navel", "abs", "biceps", "triceps", "quadriceps",
        "calf", "calves", "hamstring", "pecs", "pectoral", "deltoid", "trapezius",
        "flexible", "suggestive_fluid", "very_sweaty", "flaccid", "lube",
        "half_erect", "greek_toe", "linea_alba", "erect", "hard_nipples",
        "crossed_bandaids", "dripping", "maebari", "headless", "ejaculating",
        "pregnant_belly", "baby_bump",
    ]),
    ("衣服", [
        "clothes", "clothing", "outfit", "garment", "garments", "shirt", "dress",
        "skirt", "pants", "shorts", "sock", "socks", "stocking", "stockings",
        "thighhighs", "thighhigh", "pantyhose", "underwear", "panties", "pantsu",
        "bra", "swimsuit", "bikini", "uniform", "jacket", "coat", "sweater",
        "hoodie", "kimono", "yukata", "blazer", "tshirt", "leotard", "leggings",
        "suit", "vest", "cardigan", "tank_top", "camisole", "robe", "swim_suit",
        "school_uniform", "serafuku", "towel", "jumpsuit", "bodysuit", "sarong",
        "qipao", "cheongsam", "gym_uniform", "sportswear", "sleeveless",
        "long_sleeves", "short_sleeves", "buruma", "bloomers", "spats",
        "corset", "lingerie", "babydoll", "negligee", "garter", "garter_belt",
        "loincloth", "fundoshi", "hakama", "sari", "toga", "kilt", "overalls",
        "dungarees", "tunic", "tabard", "dress_shirt", "polo", "blouse",
        "halter", "halterneck", "tube_top", "bandeau", "bustier", "sports_bra",
        "miniskirt", "pleated_skirt", "pencil_skirt", "jeans", "hotpants",
        "booty_shorts", "briefs", "boxers", "boxer_briefs", "trunks", "speedo",
        "monokini", "tankini", "rash_guard", "wetsuit", "spacesuit", "costume",
        "cosplay", "military_uniform", "sailor_uniform", "school_swimsuit",
        "sukumizu", "maid_uniform", "waitress_uniform", "nurse_uniform",
        "police_uniform", "bikini", "swimwear", "pajamas", "sleepwear",
        "nightgown", "kigurumi", "leather_jacket", "denim", "sundress",
        "wrap_dress", "off_shoulder", "crop_top", "sweater_vest", "turtleneck",
        "parka", "anorak", "poncho", "kaftan", "djellaba", "hanfu", "hanbok",
        "ao_dai", "kebaya", "dirndl", "abaya", "burqa", "sarafan", "sundress",
        "sundress", "wedding_dress", "bridal", "gown", "dress_shirt",
        # 衣物后缀 / 更多款式
        "legwear", "sleeves", "sleeve", "armwear", "arm_warmers", "leg_warmers",
        "cuffs", "ankle_cuffs", "wrist_cuffs", "undershirt", "sash", "bib",
        "hosiery", "thong", "g-string", "g_string", "sarashi", "onesie",
        "romper", "coveralls", "raincoat", "trench_coat", "pea_coat",
        "windbreaker", "sweatshirt", "sweatpants", "joggers", "track_suit",
        "tracksuit", "swim_trunks", "board_shorts", "chaps", "button-up",
        "button_up", "zipper", "bandage_wrap", "cloth_wrap", "shirtless",
        "pantless", "bottomless", "shoeless", "barefoot", "open_shirt",
        "unbuttoned", "untucked", "sleeves_rolled", "tied_shirt", "cropped",
        "low-cut", "low_cut", "plunging_neckline", "backless", "sidedress",
        "suspender_skirt", "overalls_skirt", "jumper", "pinafore", "apron_dress",
        "smock", "smocked", "bloomers", "drawers", "petticoat", "crinoline",
        "bustle", "fishtail", "mermaid_dress", "a-line", "empire_waist",
        "princess_sleeves", "puff_sleeves", "bell_sleeves", "cape_sleeves",
        "dolman_sleeves", "raglan_sleeves", "kimono_sleeves", "slit_skirt",
        "high-low_skirt", "hi-low_skirt", "wrap_skirt", "skort", "culottes",
        "see-through", "see_through", "strapless", "highleg", "zettai_ryouiki",
        "kneehighs", "fishnets", "fishnet", "side_slit", "strap_slip",
        "pantyshot", "panty_pull", "covering_privates", "obi", "lace",
        "lace_trim", "frills", "frill", "ruffles", "ruffle", "tassel", "trim",
        "polka_dot", "plaid", "floral_print", "print", "buttons", "button",
        "pom_pom", "pom_poms", "crotchless", "formal", "casual", "highleg",
        "detached_sleeves", "detached_collar", "detached_cuffs", "thong",
        "microskirt", "micro_bikini", "slingshot", "pasties", "nipple_tape",
        "sarashi", "bandeau", "bralette", "camisole", "chemise", "teddy",
        "bodice", "corset", "waist_cincher", "bustle", "pannier", "farthingale",
        "hoop_skirt", "crinolette", "chemise", "shift_dress", "shirtdress",
        "sweater_dress", "jersey_dress", "bodycon", "bandage_dress",
        "pocket", "drawstring", "center_opening", "shrug", "cardigan",
        "cardigans", "bolero", "shrug", "stole", "boa", "muffler", "snood",
        "hood", "hooded", "hoodie", "pullover", "jumper", "sweater",
        "crew_neck", "v-neck", "v_neck", "u-neck", "boat_neck", "scoop_neck",
        "square_neck", "keyhole_neckline", "cowl_neck", "turtleneck",
        "cutoffs", "spaghetti_strap", "harness", "chest_harness", "gusset",
        "double_breasted", "kariginu", "habit", "labcoat", "latex", "nightcap",
        "single_bare_shoulder", "single_kneehigh", "hip_vent", "obijime",
        "gakuran", "tubetop", "haori", "hagoromo", "dougi", "happi",
        "loungewear", "tabi", "beltbra", "waistcoat", "tuxedo", "coattails",
        "tutu", "pinstripe_pattern", "single_vertical_stripe", "two_sided_fabric",
        "leather", "cloth", "matching_outfits", "sukajan", "plugsuit", "arm_wrap",
        "arm_strap", "shoulder_strap", "panty_straps", "pantylines", "panty_lift",
        "panty_peek", "upshirt", "upshorts", "unzipped", "partially_unzipped",
        "unzipping", "sweater_vest", "cardigan", "blazer", "trench", "poncho",
        "sarape", "serape", "kaftan", "muumuu", "kigurumi", "romper", "onesie",
        "bodysuit", "leotard", "unitard", "corset", "bustier", "camisole",
        "slip", "chemise", "teddy", "negligee", "babydoll", "nightgown",
        "pajamas", "sleepwear", "loungewear", "sweatsuit", "tracksuit",
        "joggers", "sweatpants", "hoodie", "pullover", "sweatshirt", "t-shirt",
        "polo_shirt", "henley", "turtleneck", "mock_neck", "crew_neck",
        "scoop_neck", "v_neck", "square_neck", "sweetheart_neckline",
        "halter_top", "crop_top", "tube_top", "bandeau", "bustier", "bralette",
        "sports_bra", "padded_bra", "lace_bra", "bra", "panties", "boyshorts",
        "bikini_bottom", "thong", "g_string", "boxers", "boxer_briefs",
        "briefs", "jockstrap", "lingerie", "stockings", "garter_belt",
        "suspenders", "pantyhose", "tights", "leggings", "fishnets", "kneehighs",
        "thighhighs", "socks", "ankle_socks", "crew_socks", "dress_socks",
        "lowleg", "knee_pads", "elbow_pads", "single_strap", "lapels",
        "bodystocking", "bathrobe", "reverse_bunnysuit", "kittysuit",
        "diamond_cutout", "side_cutout", "unfastened", "torn", "trefoil",
        "yagasuri", "seigaiha", "goth_fashion", "plugsuit", "sarafan",
        "maebari", "camouflage", "strap_lift", "single_strap",
    ]),
    ("姿势动作", [
        "standing", "sitting", "kneeling", "lying", "squatting", "pose",
        "posing", "arms_up", "hands_on", "hand_on", "spread_legs",
        "crossed_legs", "legs_up", "looking_back", "from_behind", "reaching",
        "hugging", "hug", "holding", "carrying", "spread", "on_back", "on_side",
        "seiza", "doggy", "missionary", "on_one_knee", "squat", "crawl",
        "crawling", "jumping", "running", "walking", "flying", "swimming",
        "fighting", "sleeping", "kneel", "sit", "stand", "bend", "bending",
        "leaning", "straddling", "riding", "kissing", "grabbing", "lifting",
        "stretching", "crouching", "reclining", "pointing", "waving",
        "thumbs_up", "peace_sign", "v_sign", "saluting", "bowing", "dance",
        "dancing", "kicking", "punching", "wrestling", "praying", "meditating",
        "arms_crossed", "crossed_arms", "hands_on_hips", "hand_on_hip",
        "arms_behind_back", "raised_arm", "akimbo", "arms_akimbo",
        "hands_behind_head", "leaning_forward", "bent_over", "on_all_fours",
        "all_fours", "fetal_position", "hugging_own_legs", "hugging_knees",
        "dogeza", "curtsy", "prone", "supine", "upside-down", "handstand",
        "headstand", "split", "splits", "backbend", "clapping", "applauding",
        "cheering", "waving", "saluting", "bowing", "curtsey", "shrugging",
        "somersault", "cartwheel", "levitating", "floating", "falling",
        "tripping", "swinging", "spinning", "twirling", "slouching",
        "hunching", "sneaking", "tiptoeing", "marching", "jogging", "sprinting",
        "lunging", "squatting", "crouch", "crawling", "diving", "surfing",
        "skiing", "skating", "cycling", "driving", "climbing", "hanging",
        "dangling", "balancing", "standing_on_one_leg", "sitting_cross-legged",
        # 成人行为 / 体位
        "69", "anal", "fellatio", "cunnilingus", "anilingus", "masturbation",
        "paizuri", "handjob", "footjob", "blowjob", "sex", "intercourse",
        "orgy", "threesome", "group_sex", "bukkake", "creampie", "facials",
        "bondage", "bdsm", "exhibitionism", "voyeurism", "fingering",
        "penetration", "insertion", "cowgirl", "reverse_cowgirl", "mating_press",
        "prone_bone", "standing_sex", "wall_sex", "bathtub_sex", "double_penetration",
        "facesitting", "rimming", "squirting", "gokkun", "incest",
        # 运动 / 活动
        "ballet", "ballerina", "baseball", "basketball", "soccer", "football",
        "tennis", "golf", "archery", "surfing", "skiing", "skating", "cycling",
        "yoga", "gymnastics", "volleyball", "badminton", "boxing", "judo",
        "karate", "fencing", "hockey", "biking", "cooking", "baking", "eating",
        "drinking", "bathing", "showering", "fishing", "hiking", "camping",
        "reading", "writing", "drawing", "singing", "playing", "aiming",
        "beckoning", "blowing", "biting", "chewing", "swallowing", "licking",
        "sucking", "nursing", "breastfeeding", "feeding", "serving", "shopping",
        "cleaning", "washing", "sweeping", "watering", "gardening", "farming",
        "building", "exercising", "training", "working", "studying", "teaching",
        "dancing", "cheering", "applauding", "clapping",
        # 手/臂/腿/头 动作
        "hand_up", "arm_up", "hands_up", "arm_at_side", "arm_support",
        "outstretched_arms", "outstretched_arm", "knees_up", "leg_up",
        "own_hands_together", "interlocked_fingers", "index_finger_raised",
        "clenched_hand", "clenched_hands", "finger_to_mouth", "mouth_hold",
        "head_tilt", "two_side_up", "one_side_up", "looking_down", "looking_up",
        "looking_to_the_side", "looking_at_another", "looking_away",
        "looking_sideways", "kiss", "tilt", "hand_on_cheek", "hand_on_chin",
        "hand_on_face", "hand_to_mouth", "finger_gun", "lifted_by_self",
        "legs", "arms", "hands", "feet", "toes", "fingers", "hips", "knees",
        "ankles", "wrists", "elbows", "shoulders", "oral", "vaginal", "facial",
        "bound", "restrained", "gag", "mouth_hold", "arms_behind_back",
        "arms_behind_head", "arms_crossed", "hands_behind_back", "hand_gesture",
        "peace_sign", "v_sign", "thumbs_up", "finger_heart", "finger_heart_gesture",
        "hand_puppet", "armpit_hold", "bridal_carry", "princess_carry",
        "piggyback", "shoulder_ride", "fireman_carry", "headlock", "arm_lock",
        "chokehold", "hair_pull", "ear_pull", "cheek_pinch", "cheek_pull",
        "nose_pinch", "chin_grab", "hand_grab", "wrist_grab", "arm_grab",
        "leg_grab", "foot_grab", "hair_grab", "tie_grab", "collar_grab",
        "shoulder_grab", "breast_grab", "butt_grab", "thigh_grab",
        "wariza", "knee_up", "contrapposto", "doggystyle", "arm_behind_head",
        "outstretched_hand", "hand_in_pocket", "head_rest", "covering_own_mouth",
        "wading", "partially_submerged", "upskirt", "dual_wielding", "smoking",
        "arms_at_sides", "arms_behind_back", "legs_together", "legs_apart",
        "hands_on_waist", "hand_on_waist", "hand_on_hip", "hands_on_hips",
        "feet_together", "toes_together", "knees_together", "squatting",
        "crouch", "hunch", "slouch", "stoop", "perching", "reclining",
        "lounging", "sprawling", "splayed", "akimbo", "on_side", "on_back",
        "on_stomach", "prone", "supine", "fetal", "curled", "huddled",
        "cowering", "flinch", "recoil", "cringe", "shrink", "huddle",
        "presenting", "straddle", "tiptoes", "tiptoe", "leg_lift", "leg_wrap",
        "outstretched_leg", "hand_to_own_mouth", "finger_in_mouth",
        "finger_in_own_mouth", "hand_over_own_mouth", "covering_face",
        "covered_face", "covered_mouth", "covering_crotch", "pulled_by_self",
        "sheet_grab", "head_grab", "ankle_grab", "crotch_grab",
        "arm_around_shoulder", "arm_around_waist", "elbow_rest", "arm_rest",
        "headpat", "shushing", "w", "double_w", "v", "double_v", "wince",
        "peeking", "peeking_out", "looking_ahead", "looking_afar",
        "looking_outside", "looking_at_object", "facing_away", "facing_another",
        "facing_down", "on_ground", "on_lap", "on_shoulder", "on_head",
        "on_roof", "in_container", "under_covers", "under_kotatsu",
        "sidesaddle", "midair", "afloat", "submerged", "full_nelson",
        "suspended_congress", "reverse_suspended_congress", "upright_straddle",
        "reverse_upright_straddle", "folded", "groping", "rape",
        "sleep_molestation", "molestation", "self_fondle", "clitoral_stimulation",
        "deepthroat", "gaping", "gangbang", "femdom", "grinding", "shibari",
        "suspension", "hogtie", "frogtie", "tribadism", "frottage",
        "spitroast", "buttjob", "bestiality", "interspecies", "pokephilia",
        "futasub", "futa_with_futa", "twincest", "selfcest", "forced_orgasm",
        "sexually_suggestive", "public_use", "public_indecency", "prostitution",
        "vore", "nipple_fuck", "hairjob", "glansjob", "peeing_self",
        "strangling", "asphyxiation", "tickling", "teasing", "humping",
        "spooning", "sandwiched", "pet_play", "petting", "poking", "slapping",
        "spanking", "molesting", "wedgie", "reach_around", "reacharound",
        "strangulation", "choking", "suffocation", "hogtied", "spread",
        "spreading", "lifting", "carrying", "bridal_carry", "princess_carry",
        "piggyback", "shoulder_ride", "kabedon", "facepalm", "head_tilt",
        "hands_up", "hand_up", "arm_up", "legs_up", "leg_up", "knees_up",
        "arms_crossed", "legs_crossed", "crossed_legs", "sitting", "kneeling",
        "squatting", "lying", "standing", "bending", "leaning", "stretching",
        "reaching", "grabbing", "holding", "gripping", "clutching", "grasping",
        "squeezing", "pinching", "pulling", "pushing", "throwing", "catching",
        "dropping", "falling", "tripping", "slipping", "sliding", "rolling",
        "spinning", "twirling", "swinging", "swaying", "bouncing", "hopping",
        "skipping", "jumping", "leaping", "vaulting", "climbing", "hanging",
        "swinging", "diving", "plunging", "sinking", "floating", "levitating",
        "flying", "soaring", "gliding", "hovering", "drifting", "floating",
        "hreesome", "taking_picture", "gagged", "yokozuwari",
        "asymmetrical_docking", "symmetrical_docking", "just_the_tip", "caught",
        "assisted_exposure", "talking", "pouring", "spilling", "pouring_onto_self",
        "stuck", "middle_finger", "finger_on_trigger", "giving", "dressing",
        "drying", "untying", "firing", "exercise", "pinned", "holstered",
        "measuring", "two_handed", "salute", "raised_fist", "freediving",
        "splashing", "spitting", "melting", "dissolving", "stepped_on",
        "hiding", "fleeing", "chasing", "in_the_face", "high_kick", "walk_in",
        "twitching", "cheek_press", "pinky_out", "fidgeting", "wiping_face",
        "open_hand", "scratching_head", "fanning_self", "swing", "swinging",
        "squirming", "wincing", "squatting", "crouching", "perching",
        "reclining", "lounging", "sprawling", "splayed", "akimbo", "on_side",
        "surrounded_by_penises", "strap_pull", "stationary_restraints",
        "uncommon_stimulation", "guiding_hand", "dripping", "netorare",
        "paint_splatter", "profanity", "spitting",
    ]),
    ("场景", [
        "indoors", "outdoors", "sky", "night", "day", "sunset", "sunrise",
        "forest", "sea", "ocean", "beach", "snow", "rain", "school", "classroom",
        "room", "bathroom", "pool", "street", "city", "field", "stars", "moon",
        "sun", "cloud", "clouds", "water", "background", "window", "door", "bed",
        "sofa", "chair", "table", "kitchen", "park", "castle", "ruin", "ruins",
        "gradient", "landscape", "scenery", "interior", "exterior", "nature",
        "mountain", "river", "lake", "garden", "rooftop", "library", "stage",
        "train", "station", "desk", "wall", "floor", "ceiling", "hallway",
        "corridor", "balcony", "apartment", "bathhouse", "elevator", "staircase",
        "stairs", "road", "bridge", "space", "underwater", "aquarium",
        "festival", "fireworks", "snowing", "raining", "cherry_blossoms",
        "autumn", "spring", "winter", "summer", "alley", "cityscape",
        "countryside", "meadow", "grassland", "desert", "cave", "dungeon",
        "church", "temple", "shrine", "hospital", "office", "store", "shop",
        "restaurant", "cafe", "bar", "gym", "playground", "amusement_park",
        "zoo", "airport", "bedroom", "living_room", "bathroom", "toilet",
        "pool", "beach", "sky", "horizon", "panorama", "vista", "island",
        "valley", "waterfall", "volcano", "iceberg", "aurora", "rainbow",
        "lightning", "storm", "wind", "fog", "mist", "dawn", "dusk", "noon",
        # 节日 / 场所
        "halloween", "christmas", "new_year", "valentine", "birthday",
        "anniversary", "easter", "hanami", "chinese_new_year", "hotel", "motel",
        "mansion", "cottage", "tower", "crosswalk", "sidewalk", "highway",
        "parking_lot", "gas_station", "supermarket", "market", "fair",
        "carnival", "concert", "wedding", "graduation", "sports_day",
        "cultural_festival", "onsen", "hot_spring", "sauna", "locker_room",
        "classroom", "infirmary", "nurse_office", "principal_office",
        "staff_room", "clubroom", "gymnasium", "auditorium", "dormitory",
        "dorm", "laboratory", "workshop", "factory", "warehouse", "dock",
        "harbor", "port", "pier", "lighthouse", "fountain", "statue_square",
        "plaza", "roundabout", "avenue", "boulevard", "alleyway", "backstreet",
        "couch", "military", "fire", "ice", "steam", "smoke", "flames",
        "sunlight", "battle", "war", "ruins", "campsite", "campfire", "bonfire",
        "fireplace", "hearth", "oven", "furnace", "volcano", "earthquake",
        "flood", "tsunami", "blizzard", "snowstorm", "sandstorm", "tornado",
        "hurricane", "thunderstorm", "meteor", "comet", "galaxy", "nebula",
        "constellation", "planet", "satellite", "spaceship", "spacestation",
        "sand", "rock", "rocks", "fence", "railing", "tiles", "bricks",
        "cobblestone", "gravel", "dirt", "mud", "puddle", "pond", "stream",
        "creek", "canal", "dam", "reservoir", "waterfall", "geyser", "glacier",
        "iceberg", "tundra", "savanna", "jungle", "rainforest", "swamp",
        "marsh", "bog", "wetland", "canyon", "gorge", "ravine", "cliff",
        "bluff", "plateau", "mesa", "dune", "oasis", "lagoon", "atoll",
        "fjord", "peninsula", "cape", "strait", "gulf", "bay",
        "tatami", "futon", "doorway", "sliding_doors", "shouji", "fusuma",
        "kotatsu", "zabuton", "bathtub", "poolside", "locker", "restroom",
        "urinal", "prison", "closet", "cupboard", "sink", "faucet", "laundry",
        "graveyard", "tombstone", "coffin", "skyscraper", "skyline", "town",
        "japan", "soviet", "egyptian", "stadium", "casino", "candlelight",
        "evening", "morning", "shade", "overcast", "light", "dark", "silhouette",
        "torii", "utility_pole", "billboard", "wire", "cable", "rubble",
        "pillar", "column", "arch", "architecture", "real_world_location",
        "east_asian_architecture", "tokyo", "tent", "hammock", "shower",
        "bathtub", "onsen", "hot_spring", "sauna", "locker_room", "infirmary",
        "nurse_office", "principal_office", "staff_room", "clubroom",
        "gymnasium", "auditorium", "dormitory", "dorm", "laboratory",
        "workshop", "factory", "warehouse", "dock", "harbor", "port", "pier",
        "lighthouse", "fountain", "statue_square", "plaza", "roundabout",
        "avenue", "boulevard", "alleyway", "backstreet", "crosswalk",
        "sidewalk", "highway", "parking_lot", "gas_station", "supermarket",
        "market", "fair", "carnival", "concert", "wedding", "graduation",
        "sports_day", "cultural_festival", "countryside", "meadow", "grassland",
        "desert", "cave", "dungeon", "church", "temple", "shrine", "hospital",
        "office", "store", "shop", "restaurant", "cafe", "bar", "gym",
        "playground", "amusement_park", "zoo", "airport", "bedroom",
        "living_room", "toilet", "island", "valley", "waterfall", "volcano",
        "iceberg", "aurora", "rainbow", "lightning", "storm", "wind", "fog",
        "mist", "dawn", "dusk", "noon", "skyline", "horizon", "panorama",
        "vista", "scenery", "landscape", "seascape", "cityscape", "streetview",
        "brick", "bath", "electricity", "horror", "condensation", "snowman",
        "contrail", "spotlight", "bubble", "air_bubble", "foam", "ripples",
        "counter", "doorstep", "steps", "threshold", "walkway", "path", "trail",
        "trick_or_treat", "karaoke", "massage_parlor", "driveway", "gate",
    ]),
    ("构图", [
        "solo", "1girl", "1boy", "2girls", "2boys", "3girls", "3boys",
        "multiple_girls", "multiple_boys", "multiple", "group", "close-up",
        "closeup", "full_body", "upper_body", "lower_body", "half_body",
        "portrait", "profile", "from_side", "from_above", "from_below",
        "looking_at_viewer", "monochrome", "greyscale", "grayscale", "sketch",
        "lineart", "transparent", "comic", "watermark", "censored", "uncensored",
        "mosaic", "pixel", "scan", "screentone", "duplicate", "frame", "bust",
        "close", "dutch_angle", "fisheye", "fish-eye", "low_angle", "high_angle",
        "viewer", "cowboy_shot", "speech_bubble", "dialogue", "text", "signature",
        "artist_name", "copyright", "parody", "meme", "reference", "fake",
        "spoiler", "review", "commentary", "flat_color", "colored", "painting",
        "watercolor", "traditional_media", "digital_media", "photo",
        "photograph", "screenshot", "wallpaper", "border", "frame", "vignette",
        "sepia", "technicolor", "poster", "cover", "header", "banner", "icon",
        "logo", "sticker", "emoji", "emoticon", "chibi", "super_deformed",
        "mini_person", "age_progression", "before_and_after", "character_name",
        # 数量 / 分格 / 风格 / 文字
        "koma", "1other", "2others", "3others", "4others", "5others", "6others",
        "others", "everyone", "4girls", "5girls", "6girls", "4boys", "5boys",
        "6boys", "style", "outline", "aged_up", "aged_down", "age_regression",
        "alternate_color", "alternate_form", "alternate_universe", "official_art",
        "fanart", "fan_art", "thought_bubble", "blank_speech_bubble",
        "english_text", "japanese_text", "chinese_text", "translated", "untranslated",
        "no_text", "text_focus", "credits", "self_parody", "colorization",
        "remaster", "hd", "high_resolution", "low_resolution", "bad_quality",
        "coloring", "rough_sketch", "clean_lineart", "ink", "watercolor",
        "copic", "gouache", "acrylic", "oil_painting", "pastel", "marker",
        "colored_pencil", "digital", "traditional", "mixed_media", "3d", "2d",
        "photorealistic", "anime_style", "manga_style", "western_style",
        "no_humans", "dated", "twitter_username", "patreon_username",
        "web_address", "username", "website", "url", "signed", "blurry", "blur",
        "motion_lines", "lens_flare", "foreshortening", "letterboxed", "pov",
        "shading", "shadow", "glowing", "glow", "light_particles", "sunlight",
        "faceless", "crossover", "science_fiction", "scifi", "abstract",
        "art_nouveau", "anime_coloring", "1koma", "2koma", "3koma", "4koma",
        "5koma", "6+girls", "6+boys", "6+others", "black_and_white",
        "greyscale", "monotone", "duotone", "sepia_tone", "noir", "pastel",
        "vibrant", "muted", "desaturated", "oversaturated", "colorful",
        "monochromatic", "sketchbook", "doodle", "chibi_only", "sd",
        "super_deformed", "meme", "reaction_image", "reaction_face",
        "exploit", "4koma", "gag_comic", "strip", "omake", "bonus",
        "shaded_face", "censoring", "spot_color", "reflection", "backlighting",
        "emphasis_lines", "notice_lines", "light_rays", "glint", "oekaki",
        "realistic", "contemporary", "page_number", "borrowed_character",
        "blue_theme", "top-down_bottom-up", "personification", "focus_lines",
        "speed_lines", "action_lines", "sound_effects", "onomatopoeia",
        "screentone", "half-tone", "halftone", "dot_screen", "crosshatching",
        "hatching", "stippling", "airbrush", "gradient", "glow_effect",
        "bloom_effect", "bloom", "overexposure", "underexposure", "contrast",
        "saturation", "color_balance", "sepia", "monochrome", "duotone",
        "tritone", "quadtone", "technicolor", "vhs_effect", "scanlines",
        "jaggy_lines", "screentones", "dithering", "glitch",
        "chromatic_aberration", "caustics", "bokeh", "vignetting",
        "vanishing_point", "perspective", "zoom_layer", "pillarboxed", "flats",
        "x_ray", "how_to", "tachi_e", "lineup", "column_lineup", "straight_on",
        "sideways", "wide_shot", "very_wide_shot", "selfie", "recording",
        "timestamp", "subtitled", "title", "lyrics", "song_name",
        "spoken_ellipsis", "spoken_question_mark", "spoken_exclamation_mark",
        "spoken_interrobang", "spoken_squiggle", "spoken_object",
        "spoken_heart", "spoken_character", "chat_log", "menu", "stats",
        "user_interface", "holographic_interface", "viewfinder",
        "gameplay_mechanics", "video_game", "ad", "product_placement",
        "brand_name_imitation", "borrowed_design", "borrowed_character",
        "cameo", "real_life_insert", "animification", "chinese", "japanese",
        "english", "korean", "language", "zzz", "still_life", "surreal",
        "rotational_symmetry", "symmetry", "pixelated", "perspective",
        "foreshortening", "focus", "back_focus", "foot_focus", "hand_focus",
        "face_focus", "top_down_bottom_up", "countdown", "page_number",
        "cross_section", "cutaway", "exploded_view", "blueprint", "schematic",
        "diagram", "chart", "graph", "infographic", "annotation", "label",
        "caption", "subtitle", "translation", "localization", "scanlation",
        "typeset", "lettering", "font", "typography", "handwriting",
        "calligraphy", "signature", "autograph", "stamp", "seal", "watermark",
        "credits", "disclaimer", "warning", "notice", "rating", "logo",
        "theme", "tally", "instant_loss", "identity_censor", "squiggle",
        "accidental_exposure", "afterimage", "magic", "magic_circle",
        "bilingual", "stain", "manga", "livestream", "confession", "graffiti",
        "explosion", "clone", "fusion", "qr_code", "barcode", "pixiv_id",
        "page_number", "cross_section", "cutaway", "close_up", "close-up",
        "fabric_emphasis", "size_difference", "convenient_leg", "convenient_arm",
        "puff_of_air", "covr", "blank_censor", "paint_splatter",
        "unmoving_pattern", "novelty_censor", "crack", "lattice", "death",
        "character_censor", "profanity", "messy", "artist_self_insert",
        "teamwork", "rounded_corners", "vignette", "hexagram", "pentagram",
    ]),
    ("人物", [
        "girl", "girls", "boy", "boys", "woman", "women", "man", "men", "loli",
        "lolita", "shota", "female", "male", "child", "children", "baby",
        "toddler", "mother", "mom", "father", "dad", "sister", "brother",
        "sibling", "siblings", "couple", "twins", "maid", "nurse", "doctor",
        "police", "policewoman", "policeman", "officer", "soldier", "witch",
        "magical_girl", "princess", "prince", "queen", "king", "emperor",
        "empress", "knight", "samurai", "ninja", "nun", "priest", "priestess",
        "bride", "groom", "angel", "demon", "devil", "elf", "fairy", "vampire",
        "werewolf", "zombie", "ghost", "robot", "android", "cyborg", "doll",
        "idol", "singer", "waitress", "waiter", "chef", "pirate", "cowboy",
        "detective", "schoolgirl", "schoolboy", "teacher", "student", "miko",
        "shrine_maiden", "mermaid", "succubus", "incubus", "oni", "yokai",
        "monster_girl", "monster_boy", "centaur", "catgirl", "cat_girl",
        "foxgirl", "fox_girl", "wolfgirl", "wolf_girl", "doggirl", "dog_girl",
        "bunnygirl", "bunny_girl", "dragon_girl", "kemonomimi", "nekomimi",
        "furry", "anthro", "androgynous", "tomboy", "bishounen", "bishoujo",
        "goddess", "deity", "sorceress", "mage", "wizard", "bard", "archer",
        "assassin", "berserker", "lancer", "rider", "caster", "saber",
        "hero", "heroine", "villain", "villainess", "tsundere", "yandere",
        "dandere", "kuudere", "cheerful", "shy", "stoic", "energetic", "naive",
        "clumsy", "airhead", "bookworm", "delinquent", "chuunibyou",
        "housemaid", "butler", "ojou", "gamer", "programmer", "scientist",
        "astronaut", "firefighter", "fireman", "postman", "farmer", "miner",
        "blacksmith", "carpenter", "mechanic", "pilot", "captain", "general",
        "president", "ceo", "businessman", "office_lady", "salaryman",
        "alien", "dancer", "musician", "athlete", "model", "actress", "actor",
        "celebrity", "dwarf", "giant", "titan", "god", "monk", "paladin",
        "druid", "ranger", "rogue", "warlock", "necromancer", "summoner",
        "alchemist", "engineer", "inventor", "professor", "principal",
        "librarian", "clerk", "receptionist", "secretary", "driver", "fisherman",
        "hunter", "thief", "bandit", "smuggler", "spy", "bodyguard", "mercenary",
        "gladiator", "wrestler", "martial_artist", "sumo", "geisha", "oiran",
        "hostess", "barmaid", "clown", "mime", "magician", "juggler", "acrobat",
        "puppeteer", "bartender", "barista", "janitor", "guard", "gatekeeper",
        "chimera", "slime", "golem", "zombie", "skeleton", "lich", "demon_girl",
        "angel_girl", "succubus_girl", "ghost_girl", "harpy", "lamia", "dullahan",
        "naga", "orc", "goblin", "troll", "ogre", "fairy_girl", "elf_girl",
        "vampire_girl", "mummy", "banshee", "valkyrie", "amazon", "cyborg_girl",
        "hetero", "yuri", "yaoi", "bara", "heterosexual", "homosexual",
        "otoko_no_ko", "futanari", "trap", "vtuber", "virtual_youtuber", "army",
        "crossdresser", "crossdressing", "lolicon", "shotacon", "genderswap",
        "gender_bend", "androgyny", "intersex", "agender", "nonbinary",
        "transgender", "transvestite", "cosplayer", "streamer", "youtuber",
        "sisters", "minigirl", "interracial", "height_difference",
        "age_difference", "dual_persona", "personification", "twins",
        "triplets", "quadruplets", "siblings", "relatives", "family",
        "parents", "grandmother", "grandfather", "grandparents", "aunt",
        "uncle", "cousin", "nephew", "niece", "stepmother", "stepfather",
        "stepsister", "stepbrother", "foster", "adopted", "orphan",
        "jiangshi", "mesugaki", "gyaru", "cheerleader", "slave", "dominatrix",
        "stripper", "yordle", "au_ra", "viera", "harvin", "kitsune", "kyuubi",
        "nekomusume", "newhalf", "milf", "giantess", "undead", "spirit",
        "shikigami", "onmyouji", "pervert", "chikan", "asian", "people",
        "crowd", "utaite", "harem", "twincest", "selfcest", "nekomimi",
        "kemonomimi", "catgirl", "foxgirl", "wolfgirl", "doggirl", "bunnygirl",
        "dragon_girl", "monster_girl", "elf_girl", "demon_girl", "angel_girl",
        "succubus", "incubus", "vampire", "werewolf", "ghost", "phantom",
        "poltergeist", "banshee", "valkyrie", "amazon", "warrior", "fighter",
        "monk", "paladin", "cleric", "druid", "ranger", "rogue", "bard",
        "sorcerer", "warlock", "necromancer", "summoner", "alchemist",
        "blacksmith", "carpenter", "merchant", "innkeeper", "bartender",
        "waitress", "waiter", "chef", "baker", "butcher", "farmer", "fisherman",
        "hunter", "miner", "lumberjack", "sailor", "pirate", "captain",
        "navigator", "helmsman", "gunner", "cannoneer", "marine", "soldier",
        "officer", "general", "admiral", "marshal", "commander", "sergeant",
        "corporal", "private", "recruit", "veteran", "mercenary", "assassin",
        "ninja", "samurai", "ronin", "knight", "squire", "page", "herald",
        "monarch", "king", "queen", "prince", "princess", "emperor", "empress",
        "duke", "duchess", "count", "countess", "baron", "baroness", "lord",
        "lady", "noble", "nobleman", "noblewoman", "aristocrat", "royalty",
        "peasant", "commoner", "villager", "citizen", "civilian", "refugee",
        "ambiguous_gender", "mind_control", "hypnosis", "sadism", "masochism",
        "corruption", "nudist", "shortstack", "lolidom", "jirai_kei", "manly",
        "tall", "old", "elderly", "femboy", "wife_and_wife", "husband_and_wife",
        "netorare", "teamwork", "player_2", "dual_persona",
    ]),
    ("物品", [
        "book", "books", "cup", "phone", "smartphone", "cellphone", "umbrella",
        "clock", "computer", "laptop", "keyboard", "monitor", "tv", "television",
        "camera", "card", "cards", "toy", "plush", "pillow", "blanket",
        "lantern", "candle", "flag", "poster", "sign", "box", "bottle", "plate",
        "dish", "tableware", "furniture", "lamp", "scissors", "key", "lock",
        "envelope", "letter", "paper", "notebook", "pen", "pencil", "crayon",
        "brush", "paintbrush", "palette", "canvas", "easel", "ruler", "eraser",
        "glue", "tape", "stapler", "binder", "clipboard", "suitcase", "luggage",
        "wallet", "coin", "banknote", "money", "cash", "credit_card", "ticket",
        "passport", "map", "compass", "binoculars", "microscope", "telescope",
        "radio", "speaker", "amplifier", "microphone", "headset", "remote",
        "controller", "game_controller", "joystick", "console", "arcade",
        "puzzle", "board_game", "chess", "cards", "dice", "domino", "ball",
        "balloon", "kite", "yo-yo", "rubik", "lego", "robot_toy", "plushie",
        "doll", "puppet", "marionette", "music_box", "gramophone", "record",
        "cd", "dvd", "cassette", "vhs", "film", "crt", "monitor", "projector",
        "typewriter", "fax", "printer", "scanner", "phone", "pager", "beeper",
        "radio", "walkman", "mp3", "ipod", "tablet", "kindle", "gadget",
        # 乐器
        "guitar", "piano", "violin", "instrument", "music", "musical", "note",
        "notes", "clef", "lute", "flute", "drum", "drums", "trumpet", "saxophone",
        "harp", "cello", "trombone", "tuba", "clarinet", "oboe", "bassoon",
        "accordion", "harmonica", "tambourine", "xylophone", "keyboard",
        "synthesizer", "turntable", "microphone", "speaker", "headphone",
        # 载具
        "aircraft", "airplane", "airship", "ship", "boat", "car", "truck",
        "bus", "motorcycle", "bicycle", "bike", "tank", "helicopter",
        "submarine", "vehicle", "scooter", "skateboard", "jet", "plane",
        "rocket", "spaceship", "yacht", "canoe", "kayak", "rowboat", "sailboat",
        "tractor", "bulldozer", "forklift", "ambulance", "fire_truck",
        "police_car", "taxi", "van", "trailer", "wagon", "sledge", "sleigh",
        "snowmobile", "train", "tram", "monorail", "zeppelin", "glider",
        # 家具 / 家用
        "armchair", "bench", "stool", "cabinet", "drawer", "shelf", "bookshelf",
        "wardrobe", "dresser", "nightstand", "mirror", "vase", "statue",
        "carpet", "rug", "curtain", "curtains", "chandelier", "lamppost",
        "streetlight", "traffic_light", "signboard", "neon_sign",
        "vending_machine", "washing_machine", "refrigerator", "oven", "stove",
        "microwave", "toaster", "kettle", "blender", "dishwasher", "vacuum",
        "sewing_machine", "air_conditioner", "heater", "radiator", "fan",
        "clock", "watch", "hourglass", "scale", "basket", "cage", "chain",
        "rope", "ladder", "barrel", "bucket", "crate", "sack", "hammer",
        "wrench", "screwdriver", "saw", "axe", "shovel", "rake", "hoe",
        "wheelbarrow", "anvil", "bellows", "forge", "pot", "pan", "teapot",
        "kettle", "mug", "glass", "bowl", "plate", "cutlery", "utensil",
        "gift", "present", "bell", "jingle_bell", "mecha", "gun", "rifle",
        "book", "comic_book", "magazine", "newspaper", "brochure", "pamphlet",
        "flyer", "poster", "blueprint", "chart", "graph", "diagram", "board",
        "whiteboard", "chalkboard", "blackboard", "bulletin_board", "calendar",
        "clock", "watch", "alarm_clock", "hourglass", "compass", "gps",
        "calculator", "abacus", "typewriter", "keyboard", "mouse", "trackpad",
        "monitor", "screen", "display", "crt", "lcd", "led", "projector",
        "camera", "camcorder", "webcam", "drone", "rc_car", "robot", "machine",
        "tray", "teacup", "cigarette", "condom", "dildo", "vibrator", "pouch",
        "innertube", "rock", "crystal", "skull", "machinery", "dakimakura",
        "can", "candle", "candlestand", "lantern", "torch", "flashlight",
        "lighter", "match", "cigarette_holder", "pipe", "bong", "ashtray",
        "hookah", "incense", "censer", "crystal_ball", "tarot", "ouija",
        "dice", "domino", "jigsaw", "rubik", "yo-yo", "kendama", "tops",
        "spinning_top", "jack", "marbles", "ball", "balloon", "bubble",
        "soap_bubble", "kite", "pinwheel", "wind_chime", "mobile",
        "needle", "syringe", "pill", "drugs", "medicine", "thermometer",
        "stethoscope", "toothbrush", "comb", "sponge", "soap", "tissue",
        "used_tissue", "napkin", "mop", "duster", "spatula", "whisk", "ladle",
        "skewer", "saucer", "flask", "test_tube", "beaker", "stylus", "notepad",
        "screw", "nail", "drill", "gears", "cog", "plug", "outlet", "gamepad",
        "nintendo_switch", "joy_con", "crane_game", "mahjong", "chessboard",
        "poker_chip", "figure", "figurine", "mannequin", "fumo", "hammock",
        "tent", "sleeping_bag", "cooler", "jar", "package", "candlestand",
        "lighter", "match", "cigar", "pipe", "hookah", "bong", "gauze",
        "wheel", "steering_wheel", "tire", "engine", "crane", "turret",
        "warship", "battleship", "spacecraft", "antenna", "scroll", "papers",
        "stamp", "ink", "inkwell", "quill", "marker", "chalk", "wheelchair",
        "stroller", "racecar", "go_kart", "surfboard", "snowboard", "skis",
        "raft", "inflatable_raft", "lifebuoy", "briefcase", "suitcase", "trunk",
        "backpack", "handbag", "purse", "wallet", "coin", "banknote", "money",
        "cash", "credit_card", "ticket", "passport", "map", "compass",
        "binoculars", "microscope", "telescope", "radio", "speaker",
        "amplifier", "microphone", "headset", "remote", "controller",
        "game_controller", "joystick", "console", "arcade", "puzzle",
        "board_game", "chess", "cards", "dice", "domino", "ball", "balloon",
        "kite", "yo_yo", "rubik", "lego", "robot_toy", "plushie", "doll",
        "puppet", "marionette", "music_box", "gramophone", "record", "cd",
        "dvd", "cassette", "vhs", "film", "crt", "projector", "typewriter",
        "fax", "printer", "scanner", "phone", "pager", "beeper", "walkman",
        "mp3", "ipod", "tablet", "kindle", "gadget", "drone", "rc_car", "robot",
        "machine", "tool", "tools", "hammer", "wrench", "screwdriver", "saw",
        "axe", "shovel", "rake", "hoe", "wheelbarrow", "anvil", "bellows",
        "forge", "pot", "pan", "teapot", "kettle", "mug", "glass", "bowl",
        "plate", "cutlery", "utensil", "chopsticks", "fork", "spoon", "knife",
        "kitchen_knife", "cleaver", "scissors", "shears", "razor", "shaver",
        "battery_indicator", "beachball", "pole", "broom", "cushion", "bolt",
        "cube", "stick", "rod", "yarn", "string", "confetti", "origami",
        "snorkel", "seatbelt", "stained_sheets", "treasure_chest", "snowman",
        "crystal_ball", "tarot", "ouija", "crystal", "gem", "stone", "pebble",
        "buzzer", "pointer", "lotion", "explosive", "paint", "super_soaker",
        "throne", "tokkuri", "sunscreen", "lotion", "cream", "chime",
    ]),
    ("食物", [
        "food", "drink", "coffee", "tea", "cake", "bread", "fruit", "candy",
        "chocolate", "rice", "dumpling", "dumplings", "sushi", "ramen", "noodle",
        "noodles", "pizza", "burger", "hamburger", "sandwich", "salad", "soup",
        "ice_cream", "icecream", "soda", "cola", "juice", "milk", "beer", "wine",
        "sake", "alcohol", "egg", "meat", "vegetable", "vegetables", "apple",
        "banana", "strawberry", "cherry", "watermelon", "grape", "grapes",
        "orange", "lemon", "peach", "carrot", "onion", "potato", "tomato",
        "broccoli", "corn", "mushroom", "cookie", "biscuit", "doughnut",
        "donut", "pancake", "waffle", "pie", "tart", "pudding", "jelly",
        "yogurt", "cheese", "butter", "honey", "jam", "snack", "meal",
        "breakfast", "lunch", "dinner", "bento", "lunchbox", "chopsticks",
        "fork", "spoon", "bowl", "curry", "steak", "bacon", "sausage", "hotdog",
        "hot_dog", "fries", "chips", "popcorn", "pretzel", "cracker", "toast",
        "cereal", "oatmeal", "muffin", "croissant", "bagel", "donut", "sundae",
        "milkshake", "smoothie", "bubble_tea", "latte", "espresso", "cappuccino",
        "popsicle", "lollipop", "gum", "candy_cane", "cotton_candy",
        "marshmallow", "jelly_beans", "gummies", "taffy", "caramel", "toffee",
        "fudge", "brownie", "macaron", "eclair", "profiterole", "cannoli",
        "baklava", "churro", "funnel_cake", "waffle", "crepe", "pancakes",
        "syrup", "honey", "jam", "marmalade", "peanut_butter", "nutella",
        "marshmallow", "smore", "s'more", "hot_cocoa", "cocoa", "matcha",
        "boba", "tapioca", "jelly", "pudding", "custard", "flan", "creme_brulee",
        "tiramisu", "cheesecake", "mousse", "souffle", "meringue", "macaroon",
        "dango", "onigiri", "pocky", "wagashi", "obento", "bento", "ramune",
        "parfait", "popsicle", "lollipop", "spaghetti", "baguette", "blueberry",
        "dessert", "snack", "candy", "sweets", "confectionery", "pastry",
        "baked_goods", "bread", "loaf", "baguette", "croissant", "bagel",
        "toast", "sandwich", "burger", "pizza", "taco", "burrito", "sushi",
        "sashimi", "ramen", "udon", "soba", "noodles", "pasta", "rice",
        "fried_rice", "curry", "stew", "soup", "salad", "steak", "roast",
        "bacon", "sausage", "ham", "egg", "omelette", "pancake", "waffle",
        "crepe", "french_toast", "cereal", "oatmeal", "porridge", "yogurt",
        "cheese", "butter", "milk", "cream", "ice_cream", "sorbet", "gelato",
        "sundae", "milkshake", "smoothie", "juice", "soda", "cola", "lemonade",
        "tea", "coffee", "latte", "espresso", "cappuccino", "hot_chocolate",
        "cocoa", "beer", "wine", "sake", "cocktail", "champagne", "whiskey",
        "vodka", "rum", "gin", "liquor", "fruit", "apple", "banana", "orange",
        "lemon", "lime", "grape", "strawberry", "cherry", "peach", "pear",
        "melon", "watermelon", "pineapple", "mango", "kiwi", "berry",
        "blueberry", "raspberry", "blackberry", "vegetable", "carrot", "potato",
        "tomato", "onion", "garlic", "pepper", "broccoli", "corn", "mushroom",
        "spinach", "lettuce", "cabbage", "celery", "cucumber", "eggplant",
        "zucchini", "pumpkin", "squash", "beans", "peas", "lentils", "tofu",
        "soy_sauce", "icing", "groceries", "suncream", "seasoning", "spice",
        "condiment", "syrup", "dressing", "gravy", "sauce", "broth", "stock",
    ]),
    ("生物", [
        "animal", "animals", "cat", "cats", "dog", "dogs", "bird", "birds",
        "fish", "dragon", "monster", "creature", "creatures", "insect", "bee",
        "butterfly", "beetle", "spider", "snake", "frog", "rabbit", "bunny",
        "fox", "wolf", "bear", "lion", "tiger", "horse", "cow", "pig", "sheep",
        "goat", "chicken", "duck", "duckling", "penguin", "dolphin", "whale",
        "shark", "turtle", "crab", "octopus", "squid", "jellyfish", "starfish",
        "snail", "mouse", "rat", "hamster", "squirrel", "deer", "elephant",
        "giraffe", "monkey", "gorilla", "panda", "koala", "raccoon", "hedgehog",
        "bat", "owl", "eagle", "hawk", "crow", "raven", "sparrow", "swan",
        "peacock", "flamingo", "dinosaur", "unicorn", "pegasus", "griffin",
        "phoenix", "tail", "ears", "horn", "horns", "antlers", "antennae",
        "fur", "feathers", "feather", "scales", "paws", "claws", "hooves",
        "fangs", "beak", "fin", "gills", "shell", "tentacle", "tentacles",
        "plant", "tree", "trees", "flower", "flowers", "leaf", "leaves",
        "grass", "vine", "vines", "cactus", "seaweed", "coral", "blossom",
        "sakura", "cherry_blossom", "mushroom", "petal", "petals", "bouquet",
        "wreath", "nest", "egg", "cocoon", "chrysalis", "larva", "caterpillar",
        # 植物
        "rose", "bamboo", "acorn", "bloom", "bud", "sprout", "fern", "moss",
        "ivy", "sunflower", "tulip", "lily", "lotus", "orchid", "daisy",
        "dandelion", "clover", "poppy", "iris_flower", "chrysanthemum",
        "wisteria", "hydrangea", "carnation", "camellia", "peony", "lavender",
        "sunflower", "morning_glory", "pine", "maple", "oak", "willow",
        "birch", "palm", "cedar", "cypress", "cherry_tree", "apple_tree",
        "berry", "berries", "nut", "nuts", "seed", "seeds", "pinecone",
        "chestnut", "walnut", "hazelnut", "bean", "beans", "pea", "peas",
        "pumpkin", "gourd", "melon", "cucumber", "eggplant", "zucchini",
        "squash", "bell_pepper", "cabbage", "lettuce", "spinach", "celery",
        "radish", "turnip", "beet", "yam", "sweet_potato", "ginger", "garlic",
        "chili", "pepper",
        # 动物（补充）
        "anglerfish", "crocodile", "alligator", "lizard", "gecko", "iguana",
        "chameleon", "salamander", "newt", "axolotl", "toad", "tadpole", "eel",
        "salmon", "tuna", "goldfish", "koi", "carp", "catfish", "swordfish",
        "stingray", "manta", "seahorse", "lobster", "shrimp", "crayfish",
        "oyster", "clam", "mussel", "scallop", "slug", "leech", "worm",
        "earthworm", "centipede", "millipede", "scorpion", "tarantula",
        "mosquito", "fly", "dragonfly", "damselfly", "cricket", "grasshopper",
        "locust", "cicada", "mantis", "praying_mantis", "cockroach", "termite",
        "ant", "wasp", "hornet", "firefly", "ladybug", "moth", "tick", "flea",
        "otter", "beaver", "weasel", "ferret", "badger", "skunk", "meerkat",
        "mongoose", "hyena", "leopard", "cheetah", "panther", "lynx", "bobcat",
        "cougar", "jaguar", "rhino", "hippo", "zebra", "camel", "llama",
        "alpaca", "donkey", "mule", "ox", "buffalo", "bison", "yak", "moose",
        "elk", "reindeer", "caribou", "gazelle", "antelope", "impala",
        "wildebeest", "warthog", "boar", "porcupine", "armadillo", "sloth",
        "anteater", "platypus", "echidna", "kangaroo", "wallaby", "koala",
        "wombat", "tasmanian_devil", "possum", "opossum", "bat", "vulture",
        "falcon", "kestrel", "seagull", "pigeon", "dove", "parrot", "parakeet",
        "cockatoo", "macaw", "toucan", "hummingbird", "woodpecker", "robin",
        "bluebird", "canary", "finch", "ostrich", "emu", "kiwi", "puffin",
        "bug", "pokemon", "creature", "monster", "beast", "kaiju", "dinosaur",
        "dragon", "wyvern", "chimera", "manticore", "hydra", "basilisk",
        "minotaur", "sphinx", "cyclops", "gorgon", "medusa", "kelpie", "siren",
        "nymph", "dryad", "satyr", "faun", "centaur", "griffin", "hippogriff",
        "shiba_inu", "seal", "tentacle_monster", "slime", "golem", "scylla",
        "octarian", "splatoon", "digimon", "pokemon", "yordle", "kitsune",
        "kyuubi", "tanuki", "okami", "inu", "neko", "usagi", "kuma", "tora",
        "ryuu", "tatsu", "hebi", "kaeru", "saru", "uma", "ushi", "tori",
        "sakana", "mushi", "chou", "hachi", "ari", "kumo", "same", "kujira",
        "iruka", "tako", "ika", "kani", "ebi", "hotaru", "kaeru", "medaka",
        "sea_creature", "marine_life", "wildlife", "fauna", "flora", "plant",
        "tree", "flower", "leaf", "grass", "fern", "moss", "ivy", "vine",
        "bamboo", "sakura", "cherry_blossom", "rose", "lily", "lotus", "tulip",
        "sunflower", "daisy", "dandelion", "clover", "poppy", "orchid",
        "wisteria", "hydrangea", "carnation", "camellia", "peony", "lavender",
        "morning_glory", "hibiscus", "chrysanthemum", "iris_flower", "holly",
        "mistletoe", "pine", "maple", "oak", "willow", "birch", "palm",
        "cedar", "cypress", "cactus", "succulent", "seaweed", "kelp", "coral",
        "mushroom", "toadstool", "fungus", "mold", "lichen", "algae",
        "suction_cups", "single_wing", "two_tails", "bush", "pawpads",
        "paw_pads", "paw", "flock", "thorns", "seashell", "shell", "carapace",
        "antler", "antlers", "horn", "horns", "tusk", "tusks", "mane",
        "mane", "spines", "quills", "bristles", "whiskers", "feelers",
        "branch", "hitodama", "flock", "swarm", "herd", "pack",
    ]),
]

# 中文子串规则（兜底：英文名缺失时的中文标签，或用户手工添加的中文标签）
TAG_CAT_CN = [
    ("表情", [
        "微笑", "笑容", "笑", "哭", "泪", "眼泪", "脸红", "害羞", "生气", "愤怒",
        "惊讶", "吃惊", "张嘴", "闭眼", "闭上的眼睛", "闭着的嘴", "吐舌", "伸舌",
        "皱眉", "悲伤", "难过", "开心", "高兴", "认真", "严肃", "痛苦", "困惑",
        "呆滞", "无表情", "坏笑", "咧嘴", "喘气", "喊叫", "尖叫", "眨眼", "噘嘴",
        "嘟嘴", "面无表情", "流口水", "打哈欠", "叹气", "低声", "傻笑",
        "圆点嘴", "圆点鼻", "三角嘴", "圆点眼", "冷汗", "青筋", "汗颜",
    ]),
    ("眼睛", [
        "眼睛", "瞳孔", "异色瞳", "蓝眼", "红眼", "绿眼", "紫眼", "金眼", "棕眼",
        "灰眼", "粉眼", "黄眼", "眼瞳", "瞳色", "独眼", "双眼", "眼珠", "眼神",
        "虹膜", "下垂眼", "上吊眼", "三白眼", "小眼", "眼被遮住", "遮住眼", "蒙眼",
    ]),
    ("配饰", [
        "发饰", "发夹", "发带", "发圈", "发箍", "发簪", "蝴蝶结", "帽子", "贝雷帽",
        "头饰", "王冠", "皇冠", "头冠", "光环", "头纱", "头盔", "耳机", "眼镜",
        "墨镜", "眼罩", "口罩", "项链", "项圈", "耳环", "耳钉", "耳坠", "戒指",
        "手链", "手镯", "手表", "脚链", "腿环", "臂环", "围巾", "领带", "领结",
        "腰带", "手套", "丝带", "缎带", "武器", "兵器", "剑", "刀", "枪", "盾",
        "鞋子", "靴", "高跟鞋", "凉鞋", "包", "背包", "伞", "扇子", "翅膀",
        "鼠耳", "耳饰", "护膝", "护肩", "护臂", "铃铛",
    ]),
    ("发型发色", [
        "长发", "短发", "双马尾", "马尾", "辫子", "呆毛", "发髻", "卷发", "直发",
        "波浪", "刘海", "发绺", "头发", "发型", "发色", "秃头", "黑发", "金发",
        "蓝发", "粉发", "白发", "红发", "棕发", "绿发", "紫发", "灰发", "银发",
        "橙发", "多色的头发", "渐变发色", "双色头发", "波波头", "团子头",
        "股辫", "双股辫", "单股辫", "辫", "侧马尾", "盘发", "编发",
    ]),
    ("身体", [
        "乳房", "巨乳", "贫乳", "乳沟", "乳头", "胸部", "胸", "臀", "屁股", "大腿",
        "小腿", "腿", "手指", "手掌", "手臂", "脚趾", "脚踝", "肚脐", "腹", "裸体",
        "裸", "皮肤", "肩", "锁骨", "舌", "嘴唇", "肌肉", "阴部", "阴茎", "阴囊",
        "阴道", "肛门", "精液", "汗珠", "唾液", "血", "痣", "雀斑", "晒痕", "细腰",
        "肚子", "受精", "阴贴", "乳贴", "全裸", "断面", "肋骨", "膝盖", "脚跟",
    ]),
    ("衣服", [
        "衣服", "服装", "连衣裙", "裙子", "短裙", "长裙", "裤", "袜", "丝袜", "裤袜",
        "连裤袜", "过膝袜", "内衣", "内裤", "胸罩", "泳装", "泳衣", "泳裤", "死库水",
        "比基尼", "制服", "校服", "水手服", "和服", "旗袍", "汉服", "洛丽塔",
        "女仆装", "兔女郎", "衬衫", "毛衣", "外套", "西装", "大衣", "夹克", "马甲",
        "背心", "短袖", "长袖", "无袖", "露背", "露肩", "吊带", "抹胸", "披风",
        "围裙", "兜帽", "婚纱", "体操服", "运动服", "紧身衣", "连体衣", "上衣",
        "下装", "短裤", "长裤", "牛仔裤", "睡衣", "校服", "军服", "唐装", "高领",
        "军装", "连体裤袜", "热裤", "泳裤", "泳衣",
    ]),
    ("姿势动作", [
        "站立", "站姿", "坐", "跪", "躺", "趴", "蹲", "姿势", "叉腰", "翘腿", "抬腿",
        "抱", "背对", "侧躺", "仰躺", "回头", "张开腿", "爬", "倒立", "剪刀腿",
        "鸭子坐", "土下座", "抱膝", "挺胸", "弯腰", "背影", "下蹲", "盘腿", "举手",
        "低头", "悬空", "侧身", "前倾", "后仰", "拿着", "看着你", "挥手", "鞠躬",
        "握手", "亲吻", "拥抱", "跑", "走", "跳", "飞", "游泳", "战斗", "踢", "打",
        "骑", "睡觉", "跪坐", "歪头", "交叉双臂", "拍手", "跳舞",
    ]),
    ("场景", [
        "室内", "室外", "天空", "夜晚", "白天", "黄昏", "森林", "海", "水", "沙滩",
        "雪", "雨", "学校", "教室", "房间", "浴室", "泳池", "街道", "城市", "草原",
        "花田", "星空", "月亮", "太阳", "云", "建筑", "窗户", "门", "床", "沙发",
        "椅子", "桌子", "厨房", "公园", "废墟", "战场", "城堡", "背景", "图书馆",
        "屋顶", "海边", "山", "河流", "夕阳", "黎明", "舞台", "电梯", "车站",
        "火车", "地铁", "草地", "花园", "阳台", "走廊", "桥", "天空", "自然",
        "澡堂", "玄关", "被窝", "榻榻米", "阳台", "庭院", "池塘", "瀑布",
    ]),
    ("构图", [
        "单人", "1个女孩", "1个男孩", "多个女孩", "多人", "双人", "群体", "全身",
        "上半身", "下半身", "特写", "半身", "侧面", "正面", "远景", "近景", "单色",
        "黑白", "线稿", "漫画", "插画", "透明背景", "分镜", "对话框", "会话气泡",
        "水印", "有码", "无码", "审核", "签名", "署名", "作者",
    ]),
    ("人物", [
        "女孩", "男孩", "女人", "男人", "少女", "少年", "萝莉", "正太", "幼女",
        "儿童", "婴儿", "学生", "老师", "护士", "医生", "警官", "警察", "军人",
        "士兵", "女仆", "女巫", "魔法少女", "魔女", "公主", "王子", "女王", "国王",
        "骑士", "武士", "忍者", "修女", "牧师", "新娘", "新郎", "天使", "恶魔",
        "精灵", "妖精", "吸血鬼", "狼人", "僵尸", "幽灵", "机器人", "人偶", "偶像",
        "歌手", "服务员", "厨师", "海盗", "牛仔", "侦探", "双胞胎", "姐妹", "兄弟",
        "恋人", "情侣", "妻子", "丈夫", "女性", "男性", "老人", "猫娘", "狐娘",
        "女神", "虚拟", "虎娘", "僵尸", "精灵", "天使",
    ]),
    ("物品", [
        "书", "杯子", "手机", "电脑", "相机", "玩具", "枕头", "蜡烛", "旗", "海报",
        "盒子", "瓶子", "盘子", "灯", "剪刀", "钥匙", "信封", "纸", "笔", "铅笔",
        "画", "行李箱", "钱包", "硬币", "地图", "望远镜", "麦克风", "球", "气球",
        "风筝", "玩偶", "打字机", "电话",
    ]),
    ("食物", [
        "食物", "饮料", "咖啡", "茶", "蛋糕", "面包", "水果", "糖果", "巧克力",
        "米饭", "饺子", "寿司", "拉面", "面条", "披萨", "汉堡", "三明治", "沙拉",
        "汤", "冰淇淋", "汽水", "果汁", "牛奶", "啤酒", "酒", "鸡蛋", "肉",
        "蔬菜", "苹果", "香蕉", "草莓", "樱桃", "西瓜", "葡萄", "橙子", "柠檬",
        "桃子", "胡萝卜", "洋葱", "土豆", "番茄", "西兰花", "饼干", "甜甜圈",
        "派", "布丁", "酸奶", "奶酪", "蜂蜜", "早餐", "午餐", "晚餐", "便当",
    ]),
    ("生物", [
        "动物", "猫", "狗", "鸟", "鱼", "龙", "怪物", "昆虫", "蜜蜂", "蝴蝶",
        "蜘蛛", "蛇", "青蛙", "兔子", "狐狸", "狼", "熊", "狮子", "老虎", "马",
        "牛", "猪", "羊", "鸡", "鸭子", "企鹅", "海豚", "鲸鱼", "鲨鱼", "乌龟",
        "螃蟹", "章鱼", "水母", "蜗牛", "老鼠", "仓鼠", "松鼠", "鹿", "大象",
        "猴子", "熊猫", "猫头鹰", "尾巴", "兽耳", "角", "羽毛", "爪子", "翅膀",
        "植物", "树", "花", "叶子", "草", "蘑菇", "珊瑚", "樱花", "花瓣",
    ]),
]


def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


# 单独出现的身体部位词（整名相等才算，避免「hands_on_hips」被误判为身体）
_BODY_PART_EXACT = {
    "hand", "hands", "arm", "arms", "leg", "legs", "foot", "feet", "toes",
    "fingers", "hip", "hips", "thigh", "thighs", "face", "ear", "ears",
    "shoulder", "shoulders", "knee", "knees", "elbow", "elbows", "ankle",
    "ankles", "wrist", "wrists", "neck", "back", "chest", "abdomen",
    "belly", "waist", "navel", "navel_piercing", "butt", "ass",
}


def _boundary_match(s: str, k: str) -> bool:
    """下划线边界匹配：k 作为完整词段出现在 s 中（含单段与多段）。"""
    return (s == k or s.startswith(k + "_") or s.endswith("_" + k)
            or ("_" + k + "_") in s)


def tag_category_en(name: str) -> str:
    """英文标签分类：按下划线边界匹配关键词（多词关键词按完整词组匹配）。"""
    s = name.strip().lower().replace("-", "_")
    if s in _EMOTICONS:
        return "表情"
    if s in _BODY_PART_EXACT:
        return "身体"
    for cat, kws in TAG_CAT_EN:
        for k in kws:
            if _boundary_match(s, k.replace("-", "_")):
                return cat
    return "其他"


def tag_category_cn(name: str) -> str:
    """中文标签分类：子串匹配（关键词以多字词为主）。"""
    s = name.strip().lower()
    for cat, kws in TAG_CAT_CN:
        for k in kws:
            if k in s:
                return cat
    return "其他"


def tag_category(name: str) -> str:
    """标签 → 分类。英文走 token 匹配，中文走子串匹配。"""
    s = (name or "").strip()
    if not s:
        return "其他"
    if _is_ascii(s):
        return tag_category_en(s)
    return tag_category_cn(s)


def parse_tags(text: str):
    if not text:
        return []
    text = text.strip().strip("`").strip()
    text = (text.replace("，", ",").replace("、", ",")
                .replace("；", ",").replace(";", ","))
    parts = re.split(r"[\n,]+", text)
    seen = set()
    tags = []
    for p in parts:
        sub_parts = re.split(r"\s+\d+[\.\)、]\s+|\s+[-*•]\s+", p.strip())
        for q in sub_parts:
            q = q.strip()
            q = re.sub(r"^\s*(?:\d+[\.\)、]|[-*•])\s*", "", q)
            q = q.strip().strip('"\'“”‘’').strip()
            if not q or len(q) > 30:
                continue
            key = normalize_tag(q)
            if key and key not in seen:
                seen.add(key)
                tags.append(key)
    return tags


def apply_tag_rules(tags):
    result = []
    for t in tags:
        key = normalize_tag(t)
        if key in NOISE_TAGS:
            continue
        if key in NSFW_WORDS:
            if "NSFW" not in result:
                result.append("NSFW")
            continue
        if t not in result:
            result.append(t)
    return result


def dhash(img: Image.Image, hash_size: int = 8):
    g = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = px[row * (hash_size + 1) + col]
            right = px[row * (hash_size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _clean_tag(tag: str) -> str:
    c = tag
    for w in REDUNDANT_TAIL:
        if c.endswith(w) and len(c) > len(w) + 1:
            c = c[: -len(w)]
            break
    for w in REDUNDANT_HEAD:
        if c.startswith(w) and len(c) > len(w) + 1:
            c = c[len(w):]
            break
    return c


def _similar(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) > len(b):
        a, b = b, a
    return len(b) - len(a) == 1 and a in b


def build_merge_map(tags, freq=None):
    freq = freq or {}
    cleaned = [_clean_tag(t) for t in tags]
    cleaned = [c for c in cleaned if c]
    uniq = list(dict.fromkeys(cleaned))
    uniq.sort(key=lambda t: (len(t), -(freq.get(t, 0)), t))
    rep_of = {}
    reps = []
    for t in uniq:
        rep = None
        for r in reps:
            if _similar(r, t):
                rep = r
                break
        if rep is not None:
            rep_of[t] = rep
        else:
            reps.append(t)
            rep_of[t] = t
    mapping = {}
    for orig in tags:
        c = _clean_tag(orig)
        mapping[orig] = rep_of.get(c, c if c else orig)
    return mapping


def merge_all_tags(tags_map):
    """对所有图片的标签做：噪声过滤 + NSFW 归一化 + 近义合并 + 去重。"""
    if not tags_map:
        return tags_map
    for k, tags in tags_map.items():
        tags_map[k] = apply_tag_rules(tags)
    all_tags = set()
    for tags in tags_map.values():
        all_tags.update(tags)
    if not all_tags:
        return tags_map
    freq = Counter()
    for tags in tags_map.values():
        freq.update(tags)
    mapping = build_merge_map(all_tags, freq)
    for k, tags in tags_map.items():
        new = []
        for t in tags:
            nt = mapping.get(t, t)
            if nt not in new:
                new.append(nt)
        tags_map[k] = new
    return tags_map


def unique_path(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    i = 1
    while True:
        cand = dest.with_name(f"{stem}_{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1


def load_eht_tags(path=None):
    if path is None:
        path = _BASE_DIR / "eht_tags.json"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data.get("tags", {}), data.get("namespaces", {})
    except Exception:
        return {}, {}


def load_danbooru_zh(csv_path=None):
    if csv_path is None:
        csv_path = _BASE_DIR / "danbooru_zh.csv"
    mapping = {}
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2 and row[0].strip() and row[1].strip():
                    mapping[row[0].strip()] = row[1].strip()
    except Exception:
        pass
    return mapping


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data):
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception:
        pass


def build_raw_cn_map(eht_tags):
    return {info["raw"]: cn for cn, info in eht_tags.items() if info.get("raw")}


def load_eva02(model_path, csv_path):
    import onnxruntime as ort
    tags = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            tags.append((row[1], row[2]))
    general = [(name, i) for i, (name, cat) in enumerate(tags) if cat == "0"]
    sess = ort.InferenceSession(model_path,
                                providers=["DmlExecutionProvider", "CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name
    return sess, inp, general


def eva02_tag_image(sess, inp, general, img_bgr, threshold=0.35):
    import cv2
    import numpy as np
    x = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    h, w = x.shape[:2]
    scale = 448 / max(h, w)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    x = cv2.resize(x, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    pad = np.full((448, 448, 3), 255, dtype=np.uint8)
    y0, x0 = (448 - nh) // 2, (448 - nw) // 2
    pad[y0:y0 + nh, x0:x0 + nw] = x
    x = pad.astype(np.float32)[None]
    out = sess.run(None, {inp: x})[0][0]
    result = {}
    for name, idx in general:
        p = float(out[idx])
        if p >= threshold:
            result[name] = p
    return result
