"""Every categorical mapping, each one derived from the full enumeration of raw values.

Keys are matched after clean_lib.key() (lowercase, punctuation collapsed). Anything
not listed raises UnmappedValue — nothing is ever silently bucketed.
"""
from clean_lib import mapper

SERVICE = mapper("service_type", {
    "wedding film": "Wedding Film", "wed film": "Wedding Film", "wedding films": "Wedding Film", "wedding": "Wedding Film",
    "photoshoot": "Photoshoot", "photo shoot": "Photoshoot", "stills": "Photoshoot",
    "music video": "Music Video", "mv": "Music Video", "music vid": "Music Video",
    "event coverage": "Event Coverage", "events": "Event Coverage", "event": "Event Coverage", "event cov": "Event Coverage",
    "studio rental": "Studio Rental", "studio": "Studio Rental", "studio hire": "Studio Rental", "rental studio": "Studio Rental",
    "commercial tvc": "Commercial / TVC", "tvc": "Commercial / TVC", "advert": "Commercial / TVC",
    "commercial": "Commercial / TVC", "tv commercial": "Commercial / TVC",
    "short film": "Short Film", "shortfilm": "Short Film",
    "corporate documentary": "Corporate Documentary", "documentary": "Corporate Documentary",
    "doc corporate": "Corporate Documentary", "corporate doc": "Corporate Documentary", "corp documentary": "Corporate Documentary",
})

STATUS = mapper("status", {
    "completed": "Completed", "complete": "Completed", "delivered": "Completed", "done": "Completed",
    "invoiced": "Invoiced", "billed": "Invoiced",
    "postponed": "Postponed", "on hold": "Postponed",
    "in production": "In Production", "wip": "In Production", "shooting": "In Production",
    "cancelled": "Cancelled", "canceled": "Cancelled", "cancel": "Cancelled", "cx": "Cancelled",
})

CITY = mapper("city", {
    "lagos": "Lagos", "lag": "Lagos", "ikeja lagos": "Lagos", "lagos ng": "Lagos",
    "abuja": "Abuja", "fct abuja": "Abuja", "abuja fct": "Abuja",
    "enugu": "Enugu", "ibadan": "Ibadan", "kano": "Kano",
    "port harcourt": "Port Harcourt", "portharcourt": "Port Harcourt", "ph": "Port Harcourt",
    "london": "London", "london uk": "London",
    "johannesburg": "Johannesburg", "dubai": "Dubai", "nairobi": "Nairobi",
    "accra": "Accra", "accra gh": "Accra",
    "atlanta": "Atlanta", "atl": "Atlanta", "atlanta ga": "Atlanta",
})

COUNTRY = mapper("country", {
    "nigeria": "Nigeria", "ng": "Nigeria",
    "united kingdom": "United Kingdom", "uk": "United Kingdom",
    "united states": "United States", "usa": "United States",
    "ghana": "Ghana", "uae": "United Arab Emirates", "south africa": "South Africa",
    "kenya": "Kenya", "canada": "Canada",
})

CLIENT_TYPE = mapper("client type", {
    "corporate": "Corporate", "corp": "Corporate", "b2b": "Corporate",
    "individual": "Individual", "indiv": "Individual", "b2c": "Individual", "person": "Individual",
})

LEAD_SOURCE = mapper("lead/acquisition source", {
    "agency partner": "Agency Partner", "referral": "Referral", "instagram": "Instagram", "walk in": "Walk-in",
    "google": "Google", "tiktok": "TikTok", "repeat client": "Repeat Client", "email": "Email",
})

CURRENCY_CODE = mapper("currency", {"ngn": "NGN", "n": "NGN", "usd": "USD", "gbp": "GBP", "eur": "EUR"})

ROLE = mapper("crew role", {r.lower(): r for r in [
    "Director of Photography", "Editor", "Art Director", "Colorist", "Gaffer", "Grip",
    "Drone Operator", "Sound Recordist", "Camera Operator", "Production Assistant"]})

EMPLOYMENT = mapper("employment_type", {"freelance": "Freelance", "staff": "Staff"})

APPROVER = mapper("approved_by", {
    "t adeyemi": "Tunde Adeyemi", "tunde adeyemi": "Tunde Adeyemi",
    "n okafor": "Ngozi Okafor", "ngozi okafor": "Ngozi Okafor",
    "ops manager": "Ops Manager",
})

CATEGORY = mapper("category", {c.lower(): c for c in [
    "Hoodie", "Lens Cloth", "Tee", "Sticker Pack", "Limited Print", "Cap", "Mug", "Poster A2", "Tote Bag", "Oversized Tee"]})

COLLECTION = mapper("collection", {
    "golden hour": "Golden Hour", "35mm club": "35mm Club", "behind the lens": "Behind The Lens",
    "harmattan drop": "Harmattan Drop", "studio basics": "Studio Basics", "lagos nights": "Lagos Nights",
    "anniversary 05": "Anniversary ’05",
})

COLOUR = mapper("colour", {c.lower(): c for c in ["Forest", "Black", "Rust", "Bone", "Navy", "Off-White", "Sand"]})

SIZE_RUN = mapper("size_run", {"s xxl": "S-XXL", "s m l xl xxl": "S-XXL", "os": "One Size", "one size": "One Size"})

SIZE = mapper("size", {"s": "S", "m": "M", "l": "L", "xl": "XL", "xxl": "XXL", "os": "One Size", "one size": "One Size"})

PAYMENT = mapper("payment_method", {
    "flutterwave": "Flutterwave", "paystack": "Paystack", "bank transfer": "Bank Transfer", "stripe": "Stripe",
    "cash": "Cash", "pos": "POS", "paypal": "PayPal",
})

SALES_CHANNEL = mapper("sales_channel", {
    "website": "Website", "web": "Website",
    "pop up": "Pop-up", "pop up shop": "Pop-up",
    "instagram": "Instagram", "ig dm": "Instagram", "instagram dm": "Instagram",
    "wholesale": "Wholesale",
})

ORDER_STATUS = mapper("order_status", {s.lower(): s for s in
                                        ["Delivered", "Shipped", "Cancelled", "Pending", "Returned", "Fulfilled"]})

REFUND_REASON = mapper("refund reason", {
    "changed mind": "Changed mind", "wrong size": "Wrong size", "late delivery": "Late delivery",
    "not as pictured": "Not as pictured", "damaged in transit": "Damaged", "damaged": "Damaged",
    "duplicate order": "Duplicate order",
})

PROCESSED_BY = mapper("processed_by", {
    "ops": "Ops", "support": "Support", "support xtrimstudios com": "Support", "auto": "Auto"})

SPEND_CHANNEL = mapper("spend channel", {
    "youtube pre roll": "YouTube Pre-roll", "google ads": "Google Ads", "tiktok ads": "TikTok Ads",
    "meta ads": "Meta Ads", "email crm": "Email / CRM", "influencer": "Influencer",
})

# Campaign labels are normalised for FORMAT only. Distinct names stay distinct — merging
# 'always_on' into 'brand_always_on' (or the two Black Friday labels) is an attribution
# decision for the analysis phase, not a cleaning fix. Candidates are listed in the log.
CAMPAIGN = mapper("campaign", {
    "harmattan drop": "harmattan_drop", "retarget q4": "retarget_q4", "always on": "always_on",
    "brand always on": "brand_always_on", "blackfriday24": "blackfriday24", "black friday": "black_friday",
    "wedding season 23": "wedding_season_23", "wedding season 24": "wedding_season_24",
    "showreel push": "showreel_push", "lagos nights launch": "lagos_nights_launch",
})

SPAM_SOURCES = {"seo monitor top", "buy traffic ru", "free seo tools xyz"}

# The 8 source groups. Referral spam lands in "Referral / Other" and is separately flagged is_spam.
SOURCE_CHANNEL = mapper("session source", {
    "google": "Google", "google com": "Google",
    "instagram": "Instagram", "ig": "Instagram",
    "fb": "Facebook / Meta", "facebook": "Facebook / Meta", "meta": "Facebook / Meta",
    "tiktok": "TikTok", "tik tok": "TikTok",
    "youtube": "YouTube", "yt": "YouTube",
    "email": "Email", "newsletter": "Email",
    "direct": "Direct",
    "referral": "Referral / Other", "vimeo": "Referral / Other", "linkedin": "Referral / Other",
    "behance": "Referral / Other", "twitter": "Referral / Other", "x com": "Referral / Other",
    "seo monitor top": "Referral / Other", "buy traffic ru": "Referral / Other", "free seo tools xyz": "Referral / Other",
})

MEDIUM = mapper("session medium", {
    "cpc": "paid", "ppc": "paid", "paid": "paid",
    "social": "social", "organic social": "social",
    "referral": "referral", "organic": "organic", "email": "email", "none": "none",
})

DEVICE = mapper("device", {"mobile": "Mobile", "smartphone": "Mobile", "desktop": "Desktop", "tablet": "Tablet"})
