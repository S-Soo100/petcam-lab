species_name: Crested Gecko (Correlophus ciliatus)

available_classes:
  - eating_paste: licking fruit puree (CGD/MRP/Pangea/Repashy) from a small dish. ALL of the following REQUIRED: (a) the food dish is clearly visible in the same frame as the gecko's head, (b) the tongue tip is seen physically touching the dish/paste surface (not hovering above it), (c) at least 2-3 repeated licks within the clip — a single tongue flick near the dish is sensing, not eating. If head is positioned over the dish but no tongue-to-paste contact is observed, classify as `moving`. **MOST COMMON FALSE POSITIVE — DO NOT MAKE THIS ERROR:** the gecko is near or facing the dish, body posture and orientation suggest feeding, but NO tongue-to-paste contact actually occurs in the clip. Proximity and posture are NOT evidence. If you cannot point to a specific second in the clip where the tongue contacts paste with visible repetition, the answer is `moving`.
  - eating_prey: actively hunting/biting live insects (crickets, dubia roaches). Open-mouth lunge, fast head movement, often followed by chewing. A focused stare at prey without a strike is NOT eating_prey — wait for the bite/lunge before classifying.
  - drinking: tongue contacts water — water droplets on glass/walls/leaves, or clear liquid in a water dish. KEY DISTINCTION from eating_paste: water is a TRANSPARENT wet surface (you can see through it, droplets reflect/refract light, no opaque coloring). Paste is OPAQUE (cannot see through it, fills a dish). A SINGLE clear lick of a wet surface IS drinking — water transfer needs only one contact, unlike paste which requires repeated licking. The gecko's own eye-licking is NOT drinking.
  - defecating: tail base lifts, white-tipped feces extruded, often on a perch or near the back wall. Brief event (a few seconds).
  - basking: motionless under heat source (UVB/halogen). Crested geckos are not strong baskers — usually low-effort, near hide. Do not confuse with general resting under no light.
  - hiding: animal is INSIDE a hide/cover (coco hut, dense plant, hammock interior) and STATIONARY. NOT just partial leaf occlusion while doing something else. NOT walking toward a hide.
  - moving: general locomotion — climbing, walking on substrate, jumping. Includes head movement, body shifting, or tongue flicking for environmental sensing without a food/water source.
  - unseen: nothing identifiable. Use ONLY when (a) gecko is entirely off-screen the whole clip, OR (b) only an unidentifiable fragment (single tail tip, blurred shadow) is visible with no activity. If the gecko appears even briefly (a few seconds) with body identifiable and ANY movement observable, classify as `moving` instead — brief visibility is still movement.

species_specific_notes: |
  Crested geckos are nocturnal and arboreal.
  CRITICAL — Tongue movement does NOT automatically mean eating or drinking:
    - Geckos lick their own eyes/face to clean them (no eyelids). NOT drinking.
    - Tongue flicking into the air or onto surfaces is environmental sensing (chemoreception). NOT eating.
    - "Inspecting food" pattern: gecko approaches dish, looks at it, may flick tongue once or twice, then leaves without eating. This is `moving`, NOT `eating_paste`.
    - Asymmetric proof requirements: eating_paste/eating_prey require REPEATED contact (≥2-3 licks/bites). drinking requires only ONE clear tongue-to-water contact (water transfers in a single lick).
    - When in doubt and there is no visible food/water source, default to `moving`.
    - If only the tail or unidentifiable fragment is visible with NO movement, use `unseen`. But if even briefly you see the body moving (walking, climbing, descending), use `moving` — short visibility ≠ unseen.
  Wet-surface drinking pattern (commonly missed by classifiers):
    - In humid enclosures, water condenses on glass walls and leaves. Geckos drink by licking these droplets, often a single quick lick rather than repeated drinking from a bowl.
    - If you see the tongue extend to a glass/wall/leaf surface that visibly has water droplets or a wet sheen, classify as `drinking` (single lick is sufficient — see asymmetric proof above).
    - Do NOT classify wet-glass licking as `eating_paste` — paste is opaque, contained in a dish, and lacks the reflective wet-glass appearance.
  CGD paste is the standard diet (~80% of feeding events). Live prey is occasional.
  Adult lily-axanthic morph in this footage: pale yellow base, reduced pigmentation, dark pinstripe.
  IR night vision frames are grayscale — colors are not informative at night.
  When the gecko is partially behind a leaf but the head/feet are visible doing something specific (e.g., licking a visible dish), prefer the action class over `hiding`. Mere partial occlusion is NOT hiding.
