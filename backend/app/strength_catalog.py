"""Eingebaute Übungen. Aliase sind die Namen in Hevy und Strong (englisch), damit Importe ohne Nacharbeit passen.

Felder: key, deutscher Name, Ausrüstung, Hauptmuskel, Nebenmuskeln, Art, Aliase
Art: weight_reps (Gewicht × Wdh.), bodyweight (nur Wdh.), weighted_bw (Zusatzgewicht), assisted_bw (Unterstützung),
duration (Zeit), distance (Strecke und Zeit)
"""

MUSCLES = {
    "chest": "Brust", "shoulders": "Schultern", "triceps": "Trizeps", "biceps": "Bizeps", "forearms": "Unterarme",
    "lats": "Latissimus", "upper_back": "Oberer Rücken", "traps": "Nacken (Trapez)", "lower_back": "Unterer Rücken",
    "abs": "Bauch", "glutes": "Gesäß", "quads": "Oberschenkel vorn", "hamstrings": "Oberschenkel hinten",
    "calves": "Waden", "adductors": "Adduktoren", "abductors": "Abduktoren", "neck": "Hals", "cardio": "Ausdauer",
    "full_body": "Ganzkörper", "other": "Sonstiges",
}
# Grobe Gruppen für die Verteilung (wie die Körperkarte in Hevy)
MUSCLE_GROUPS = {
    "chest": "Brust", "shoulders": "Schultern", "triceps": "Arme", "biceps": "Arme", "forearms": "Arme",
    "lats": "Rücken", "upper_back": "Rücken", "traps": "Rücken", "lower_back": "Rücken", "abs": "Rumpf",
    "glutes": "Beine", "quads": "Beine", "hamstrings": "Beine", "calves": "Beine", "adductors": "Beine",
    "abductors": "Beine", "neck": "Rücken", "cardio": "Ausdauer", "full_body": "Ganzkörper", "other": "Sonstiges",
}
EQUIPMENT = {
    "barbell": "Langhantel", "dumbbell": "Kurzhantel", "machine": "Maschine", "cable": "Kabelzug",
    "bodyweight": "Körpergewicht", "kettlebell": "Kettlebell", "band": "Band", "plate": "Hantelscheibe",
    "smith": "Multipresse", "ez_bar": "SZ-Stange", "other": "Sonstiges",
}
KINDS = {
    "weight_reps": "Gewicht × Wiederholungen", "bodyweight": "Körpergewicht (Wiederholungen)",
    "weighted_bw": "Körpergewicht + Zusatzgewicht", "assisted_bw": "Körpergewicht mit Unterstützung",
    "duration": "Dauer", "distance": "Strecke und Dauer",
}

_C = [
    # Brust
    ("bench_press", "Bankdrücken (Langhantel)", "barbell", "chest", ["triceps", "shoulders"], "weight_reps", ["Bench Press (Barbell)"]),
    ("bench_press_db", "Bankdrücken (Kurzhantel)", "dumbbell", "chest", ["triceps", "shoulders"], "weight_reps", ["Bench Press (Dumbbell)"]),
    ("incline_bench", "Schrägbankdrücken (Langhantel)", "barbell", "chest", ["shoulders", "triceps"], "weight_reps", ["Incline Bench Press (Barbell)"]),
    ("incline_bench_db", "Schrägbankdrücken (Kurzhantel)", "dumbbell", "chest", ["shoulders", "triceps"], "weight_reps", ["Incline Bench Press (Dumbbell)"]),
    ("decline_bench", "Negativbankdrücken (Langhantel)", "barbell", "chest", ["triceps"], "weight_reps", ["Decline Bench Press (Barbell)"]),
    ("bench_smith", "Bankdrücken (Multipresse)", "smith", "chest", ["triceps", "shoulders"], "weight_reps", ["Bench Press (Smith Machine)"]),
    ("chest_press", "Brustpresse (Maschine)", "machine", "chest", ["triceps", "shoulders"], "weight_reps", ["Chest Press (Machine)"]),
    ("fly_db", "Fliegende (Kurzhantel)", "dumbbell", "chest", ["shoulders"], "weight_reps", ["Chest Fly (Dumbbell)", "Dumbbell Fly"]),
    ("pec_deck", "Butterfly (Maschine)", "machine", "chest", ["shoulders"], "weight_reps", ["Butterfly (Pec Deck)", "Chest Fly (Machine)"]),
    ("cable_fly", "Cable Crossover", "cable", "chest", ["shoulders"], "weight_reps", ["Cable Fly Crossovers", "Cable Crossover", "Chest Fly (Cable)"]),
    ("push_up", "Liegestütze", "bodyweight", "chest", ["triceps", "shoulders"], "bodyweight", ["Push Up", "Push Ups"]),
    ("dips_chest", "Dips (Brust)", "bodyweight", "chest", ["triceps", "shoulders"], "weighted_bw", ["Chest Dip", "Dips"]),
    # Rücken
    ("deadlift", "Kreuzheben (Langhantel)", "barbell", "lower_back", ["glutes", "hamstrings", "traps", "forearms"], "weight_reps", ["Deadlift (Barbell)", "Deadlift"]),
    ("rdl", "Rumänisches Kreuzheben (Langhantel)", "barbell", "hamstrings", ["glutes", "lower_back"], "weight_reps", ["Romanian Deadlift (Barbell)"]),
    ("rdl_db", "Rumänisches Kreuzheben (Kurzhantel)", "dumbbell", "hamstrings", ["glutes", "lower_back"], "weight_reps", ["Romanian Deadlift (Dumbbell)"]),
    ("sumo_deadlift", "Sumo-Kreuzheben", "barbell", "glutes", ["quads", "hamstrings", "lower_back"], "weight_reps", ["Sumo Deadlift"]),
    ("pull_up", "Klimmzüge", "bodyweight", "lats", ["biceps", "upper_back"], "weighted_bw", ["Pull Up", "Pull Ups", "Pull Up (Weighted)"]),
    ("chin_up", "Klimmzüge (Untergriff)", "bodyweight", "lats", ["biceps"], "weighted_bw", ["Chin Up", "Chin Ups"]),
    ("assisted_pull_up", "Klimmzüge mit Unterstützung", "machine", "lats", ["biceps"], "assisted_bw", ["Assisted Pull Up", "Pull Up (Assisted)"]),
    ("lat_pulldown", "Latzug (Kabel)", "cable", "lats", ["biceps", "upper_back"], "weight_reps", ["Lat Pulldown (Cable)", "Lat Pulldown"]),
    ("lat_pulldown_close", "Latzug eng (Kabel)", "cable", "lats", ["biceps"], "weight_reps", ["Lat Pulldown - Close Grip (Cable)"]),
    ("lat_pulldown_machine", "Latzug (Maschine)", "machine", "lats", ["biceps"], "weight_reps", ["Lat Pulldown (Machine)"]),
    ("bent_over_row", "Vorgebeugtes Rudern (Langhantel)", "barbell", "upper_back", ["lats", "biceps", "lower_back"], "weight_reps", ["Bent Over Row (Barbell)", "Barbell Row"]),
    ("db_row", "Einarmiges Rudern (Kurzhantel)", "dumbbell", "upper_back", ["lats", "biceps"], "weight_reps", ["Dumbbell Row", "Bent Over Row (Dumbbell)"]),
    ("seated_row", "Rudern sitzend (Kabel)", "cable", "upper_back", ["lats", "biceps"], "weight_reps", ["Seated Cable Row - V Grip (Cable)", "Seated Row (Cable)", "Seated Cable Row - Bar Grip"]),
    ("machine_row", "Rudern (Maschine)", "machine", "upper_back", ["lats", "biceps"], "weight_reps", ["Seated Row (Machine)", "Iso-Lateral Row (Machine)"]),
    ("t_bar_row", "T-Bar-Rudern", "barbell", "upper_back", ["lats", "biceps"], "weight_reps", ["T Bar Row"]),
    ("pendlay_row", "Pendlay-Rudern", "barbell", "upper_back", ["lats", "lower_back"], "weight_reps", ["Pendlay Row (Barbell)"]),
    ("face_pull", "Face Pulls", "cable", "shoulders", ["upper_back", "traps"], "weight_reps", ["Face Pull", "Face Pull (Cable)"]),
    ("shrug", "Shrugs (Kurzhantel)", "dumbbell", "traps", ["forearms"], "weight_reps", ["Shrug (Dumbbell)"]),
    ("shrug_bb", "Shrugs (Langhantel)", "barbell", "traps", ["forearms"], "weight_reps", ["Shrug (Barbell)"]),
    ("back_extension", "Rückenstrecker (Hyperextension)", "bodyweight", "lower_back", ["glutes", "hamstrings"], "weighted_bw", ["Back Extension (Hyperextension)", "Back Extension", "Hyperextension"]),
    ("straight_arm_pulldown", "Überzüge am Kabel", "cable", "lats", [], "weight_reps", ["Straight Arm Lat Pulldown (Cable)"]),
    ("pullover_db", "Überzüge (Kurzhantel)", "dumbbell", "lats", ["chest"], "weight_reps", ["Pullover (Dumbbell)"]),
    # Schultern
    ("ohp", "Schulterdrücken stehend (Langhantel)", "barbell", "shoulders", ["triceps"], "weight_reps", ["Overhead Press (Barbell)", "Overhead Press", "Military Press"]),
    ("shoulder_press_db", "Schulterdrücken (Kurzhantel)", "dumbbell", "shoulders", ["triceps"], "weight_reps", ["Shoulder Press (Dumbbell)", "Seated Shoulder Press (Dumbbell)"]),
    ("shoulder_press_machine", "Schulterdrücken (Maschine)", "machine", "shoulders", ["triceps"], "weight_reps", ["Shoulder Press (Machine Plates)", "Shoulder Press (Machine)"]),
    ("arnold_press", "Arnold Press", "dumbbell", "shoulders", ["triceps"], "weight_reps", ["Arnold Press (Dumbbell)"]),
    ("lateral_raise", "Seitheben (Kurzhantel)", "dumbbell", "shoulders", [], "weight_reps", ["Lateral Raise (Dumbbell)"]),
    ("lateral_raise_cable", "Seitheben (Kabel)", "cable", "shoulders", [], "weight_reps", ["Lateral Raise (Cable)", "Single Arm Lateral Raise (Cable)"]),
    ("lateral_raise_machine", "Seitheben (Maschine)", "machine", "shoulders", [], "weight_reps", ["Lateral Raise (Machine)"]),
    ("front_raise", "Frontheben (Kurzhantel)", "dumbbell", "shoulders", [], "weight_reps", ["Front Raise (Dumbbell)"]),
    ("rear_delt_fly", "Reverse Flys (Kurzhantel)", "dumbbell", "shoulders", ["upper_back"], "weight_reps", ["Rear Delt Reverse Fly (Dumbbell)", "Reverse Fly (Dumbbell)"]),
    ("reverse_pec_deck", "Reverse Butterfly (Maschine)", "machine", "shoulders", ["upper_back"], "weight_reps", ["Rear Delt Reverse Fly (Machine)", "Reverse Fly (Machine)"]),
    ("upright_row", "Aufrechtes Rudern", "barbell", "shoulders", ["traps"], "weight_reps", ["Upright Row (Barbell)"]),
    # Arme
    ("curl_bb", "Bizepscurls (Langhantel)", "barbell", "biceps", ["forearms"], "weight_reps", ["Bicep Curl (Barbell)", "Barbell Curl"]),
    ("curl_db", "Bizepscurls (Kurzhantel)", "dumbbell", "biceps", ["forearms"], "weight_reps", ["Bicep Curl (Dumbbell)", "Dumbbell Curl"]),
    ("curl_ez", "Bizepscurls (SZ-Stange)", "ez_bar", "biceps", ["forearms"], "weight_reps", ["EZ Bar Biceps Curl", "Bicep Curl (EZ Bar)"]),
    ("curl_cable", "Bizepscurls (Kabel)", "cable", "biceps", [], "weight_reps", ["Bicep Curl (Cable)"]),
    ("hammer_curl", "Hammercurls (Kurzhantel)", "dumbbell", "biceps", ["forearms"], "weight_reps", ["Hammer Curl (Dumbbell)"]),
    ("preacher_curl", "Scottcurls", "ez_bar", "biceps", [], "weight_reps", ["Preacher Curl (Barbell)", "Preacher Curl (Machine)", "Preacher Curl (Dumbbell)"]),
    ("incline_curl", "Schrägbank-Curls (Kurzhantel)", "dumbbell", "biceps", [], "weight_reps", ["Seated Incline Curl (Dumbbell)"]),
    ("concentration_curl", "Konzentrationscurls", "dumbbell", "biceps", [], "weight_reps", ["Concentration Curl"]),
    ("triceps_pushdown", "Trizepsdrücken am Kabel", "cable", "triceps", [], "weight_reps", ["Triceps Pushdown", "Triceps Rope Pushdown", "Tricep Pushdown"]),
    ("overhead_triceps", "Trizepsdrücken über Kopf (Kabel)", "cable", "triceps", [], "weight_reps", ["Overhead Triceps Extension (Cable)", "Triceps Extension (Cable)"]),
    ("overhead_triceps_db", "Trizepsdrücken über Kopf (Kurzhantel)", "dumbbell", "triceps", [], "weight_reps", ["Overhead Triceps Extension (Dumbbell)", "Triceps Extension (Dumbbell)"]),
    ("skullcrusher", "French Press (SZ-Stange)", "ez_bar", "triceps", [], "weight_reps", ["Skullcrusher (Barbell)", "Skullcrusher (Dumbbell)", "Lying Triceps Extension"]),
    ("close_grip_bench", "Enges Bankdrücken", "barbell", "triceps", ["chest", "shoulders"], "weight_reps", ["Close Grip Bench Press", "Bench Press - Close Grip (Barbell)"]),
    ("dips_triceps", "Dips (Trizeps)", "bodyweight", "triceps", ["chest", "shoulders"], "weighted_bw", ["Triceps Dip", "Bench Dip"]),
    ("assisted_dip", "Dips mit Unterstützung", "machine", "triceps", ["chest"], "assisted_bw", ["Assisted Dip", "Dip (Assisted)"]),
    ("wrist_curl", "Handgelenkcurls", "dumbbell", "forearms", [], "weight_reps", ["Wrist Curl (Dumbbell)", "Wrist Curl (Barbell)"]),
    # Beine
    ("squat", "Kniebeugen (Langhantel)", "barbell", "quads", ["glutes", "hamstrings", "lower_back"], "weight_reps", ["Squat (Barbell)", "Back Squat", "Squat"]),
    ("front_squat", "Frontkniebeugen", "barbell", "quads", ["glutes", "abs"], "weight_reps", ["Front Squat"]),
    ("goblet_squat", "Goblet Squat", "dumbbell", "quads", ["glutes"], "weight_reps", ["Goblet Squat"]),
    ("hack_squat", "Hackenschmidt-Kniebeugen", "machine", "quads", ["glutes"], "weight_reps", ["Hack Squat (Machine)", "Hack Squat"]),
    ("smith_squat", "Kniebeugen (Multipresse)", "smith", "quads", ["glutes"], "weight_reps", ["Squat (Smith Machine)"]),
    ("leg_press", "Beinpresse", "machine", "quads", ["glutes", "hamstrings"], "weight_reps", ["Leg Press (Machine)", "Leg Press", "Leg Press Horizontal (Machine)"]),
    ("leg_extension", "Beinstrecker (Maschine)", "machine", "quads", [], "weight_reps", ["Leg Extension (Machine)", "Leg Extension"]),
    ("leg_curl_lying", "Beinbeuger liegend", "machine", "hamstrings", ["calves"], "weight_reps", ["Lying Leg Curl (Machine)"]),
    ("leg_curl_seated", "Beinbeuger sitzend", "machine", "hamstrings", [], "weight_reps", ["Seated Leg Curl (Machine)", "Leg Curl"]),
    ("lunge_db", "Ausfallschritte (Kurzhantel)", "dumbbell", "quads", ["glutes", "hamstrings"], "weight_reps", ["Lunge (Dumbbell)", "Walking Lunge (Dumbbell)"]),
    ("lunge_bb", "Ausfallschritte (Langhantel)", "barbell", "quads", ["glutes", "hamstrings"], "weight_reps", ["Lunge (Barbell)"]),
    ("bulgarian_split_squat", "Bulgarische Kniebeugen", "dumbbell", "quads", ["glutes"], "weight_reps", ["Bulgarian Split Squat"]),
    ("step_up", "Step-ups", "dumbbell", "quads", ["glutes"], "weight_reps", ["Step Up"]),
    ("hip_thrust", "Hip Thrust (Langhantel)", "barbell", "glutes", ["hamstrings"], "weight_reps", ["Hip Thrust (Barbell)"]),
    ("hip_thrust_machine", "Hip Thrust (Maschine)", "machine", "glutes", ["hamstrings"], "weight_reps", ["Hip Thrust (Machine)"]),
    ("glute_bridge", "Glute Bridge", "bodyweight", "glutes", ["hamstrings"], "weighted_bw", ["Glute Bridge"]),
    ("hip_abduction", "Abduktoren (Maschine)", "machine", "abductors", ["glutes"], "weight_reps", ["Hip Abduction (Machine)"]),
    ("hip_adduction", "Adduktoren (Maschine)", "machine", "adductors", [], "weight_reps", ["Hip Adduction (Machine)"]),
    ("calf_raise_standing", "Wadenheben stehend", "machine", "calves", [], "weight_reps", ["Standing Calf Raise (Machine)", "Standing Calf Raise", "Calf Raise"]),
    ("calf_raise_seated", "Wadenheben sitzend", "machine", "calves", [], "weight_reps", ["Seated Calf Raise", "Seated Calf Raise (Machine)"]),
    ("calf_press", "Wadendrücken (Beinpresse)", "machine", "calves", [], "weight_reps", ["Calf Press on Leg Press", "Calf Press (Machine)"]),
    ("good_morning", "Good Mornings", "barbell", "hamstrings", ["lower_back", "glutes"], "weight_reps", ["Good Morning (Barbell)"]),
    ("kb_swing", "Kettlebell Swings", "kettlebell", "glutes", ["hamstrings", "lower_back"], "weight_reps", ["Kettlebell Swing"]),
    ("bodyweight_squat", "Kniebeugen (Körpergewicht)", "bodyweight", "quads", ["glutes"], "bodyweight", ["Bodyweight Squat", "Air Squat"]),
    # Rumpf
    ("plank", "Unterarmstütz (Plank)", "bodyweight", "abs", [], "duration", ["Plank"]),
    ("side_plank", "Seitstütz", "bodyweight", "abs", [], "duration", ["Side Plank"]),
    ("crunch", "Crunches", "bodyweight", "abs", [], "bodyweight", ["Crunch"]),
    ("cable_crunch", "Crunches am Kabel", "cable", "abs", [], "weight_reps", ["Cable Crunch"]),
    ("crunch_machine", "Bauchmaschine", "machine", "abs", [], "weight_reps", ["Crunch (Machine)"]),
    ("leg_raise_hanging", "Beinheben hängend", "bodyweight", "abs", [], "bodyweight", ["Hanging Leg Raise", "Hanging Knee Raise"]),
    ("leg_raise_lying", "Beinheben liegend", "bodyweight", "abs", [], "bodyweight", ["Lying Leg Raise", "Leg Raise"]),
    ("russian_twist", "Russian Twist", "bodyweight", "abs", [], "weighted_bw", ["Russian Twist"]),
    ("ab_wheel", "Bauchroller", "other", "abs", ["lower_back"], "bodyweight", ["Ab Wheel"]),
    ("sit_up", "Sit-ups", "bodyweight", "abs", [], "bodyweight", ["Sit Up"]),
    ("dead_bug", "Dead Bug", "bodyweight", "abs", [], "bodyweight", ["Dead Bug"]),
    ("pallof_press", "Pallof Press", "cable", "abs", [], "weight_reps", ["Pallof Press"]),
    # Ganzkörper und Ausdauer
    ("clean", "Umsetzen (Power Clean)", "barbell", "full_body", ["quads", "traps", "glutes"], "weight_reps", ["Power Clean", "Clean"]),
    ("thruster", "Thruster", "barbell", "full_body", ["quads", "shoulders"], "weight_reps", ["Thruster (Barbell)"]),
    ("burpee", "Burpees", "bodyweight", "full_body", ["chest", "quads"], "bodyweight", ["Burpee"]),
    ("farmers_walk", "Farmer's Walk", "dumbbell", "forearms", ["traps", "full_body"], "weight_reps", ["Farmers Walk"]),
    ("jump_rope", "Seilspringen", "other", "cardio", ["calves"], "duration", ["Jump Rope"]),
    ("treadmill", "Laufband", "machine", "cardio", [], "distance", ["Treadmill", "Running"]),
    ("rowing_machine", "Rudergerät", "machine", "cardio", ["upper_back", "quads"], "distance", ["Rowing Machine", "Rowing"]),
    ("bike_erg", "Ergometer (Rad)", "machine", "cardio", ["quads"], "distance", ["Cycling", "Stationary Bike", "Spinning"]),
    ("elliptical", "Crosstrainer", "machine", "cardio", [], "distance", ["Elliptical Trainer"]),
    ("stair_climber", "Stepper", "machine", "cardio", ["glutes", "calves"], "duration", ["Stair Machine", "Stair Climber"]),
]

CATALOG = [
    {"key": k, "name": n, "equipment": eq, "primary": p, "secondary": s, "kind": kind, "aliases": al}
    for k, n, eq, p, s, kind, al in _C
]
