# Open Photo — Embedding Cluster Analysis
*Generated: 2026-03-11 | Model: KMeans k=50 | Embedding space: 512-dim CLIP, cosine-normalized*

## Method
- 7,015 photos with CLIP embeddings
- Embeddings L2-normalized (cosine similarity → euclidean distance)
- KMeans k=50, random_state=42, n_init=5
- Cohesion = avg cosine similarity of members to cluster centroid
- Also explored: DBSCAN (eps=0.5–0.8), KMeans k=12 and k=30

---

## Clusters Sorted by Cohesion

### Ultra-tight (cohesion > 0.75) — highly specific, visually narrow

**C19 n=117 cohesion=0.921** — Prescription bottles on bookshelves  
The tightest cluster in the collection. Same shelf, same setup, photographed repeatedly. Unmistakably specific motif.

**C04 n=96 cohesion=0.807** — Your cats  
Tabby, close-ups, on beds, warm red light. Not generic "cats" — appears to be the same animal(s).

**C03 n=227 cohesion=0.788** — Explicit NSFW content  
Many refused captions. Most explicit cluster.

**C39 n=103 cohesion=0.744** — Performers / theatrical posing  
Women on stage, microphones, sequined outfits, less explicit but provocative. Theatrical rather than private.

**C07 n=254 cohesion=0.734** — Dark abstract aesthetic  
Light trails, fractals, geometric patterns, skeletons in labs. Your "dark aesthetic" bucket.

---

### Strong cohesion (0.65–0.75) — clear themes

**C13 n=107 cohesion=0.724** — Women in candid/intimate settings  
Lying on beds, with dogs, relaxed, contemplative. Personal/candid feel vs. posed.

**C46 n=151 cohesion=0.723** — Women outdoors, editorial  
Tropical settings, bold makeup, confident poses, fashion-forward.

**C16 n=66 cohesion=0.689** — Underwater / ocean  
Scuba divers, octopus, whales, manta rays, sharks. Very pure nature sub-cluster.

**C41 n=169 cohesion=0.668** — Fine art and painting  
Abstract canvases, gallery spaces, Hindu deity art, color field painting.

**C28 n=133 cohesion=0.658** — Dogs specifically  
German shepherds, puppies, blue-eyed dogs. Separated from cats cluster.

**C24 n=156 cohesion=0.701** — Dark/dim interiors  
Fried chicken on plates, people lying on beds, abstract textures. Oddly intimate. Possibly late-night domestic.

**C02 n=79 cohesion=0.694** — Space / cosmos  
Planets, debris clouds, Tesla Roadster in orbit, solar prominences. Very tight.

**C05 n=151 cohesion=0.616** — Surreal creatures and mythology  
Ouroboros, fog-beasts, soldiers in strange landscapes, mythological illustration.

**C33 n=97 cohesion=0.640** — Comics / sci-fi illustration  
Larry Niven schematics (The Lying Bastard from Ringworld is in here), Spider-Man, Batman parody.

**C14 n=108 cohesion=0.646** — Women at events / red carpets  
Formal dresses, composed, polished. Event photography.

**C09 n=119 cohesion=0.641** — Women at press / fashion events  
Orange dress, red carpet, poised. Overlaps with C14 but distinct enough to separate.

**C01 n=201 cohesion=0.646** — Mixed gender scenes  
Office settings, humor, period costumes, apes in suits. Narrative/character-driven.

**C38 n=182 cohesion=0.633** — Young women, casual/sporty  
Bikinis, cigarettes, boxing gyms, sci-fi costumes. More youth/subculture than editorial.

**C32 n=129 cohesion=0.633** — Couples and intimate scenes  
Bars, porches, kissing, behind-the-scenes. Relationship context.

**C34 n=181 cohesion=0.631** — Wildlife on land  
Giraffes, puffins, wolves, elephants. Separated from ocean wildlife.

**C31 n=203 cohesion=0.635** — Trump specifically  
Memes, Time parodies, courtroom scenes, political figures gathered. One-person cluster.

**C35 n=192 cohesion=0.626** — Horror imagery  
Elongated creatures, dark pits, horror movie posters, unsettling figures.

**C43 n=42 cohesion=0.626** — Your own game screenshots  
Chess.com (username FAHRENHEIT visible) and Words With Friends. You photographed your own games.

**C20 n=165 cohesion=0.623** — Storm systems / dramatic weather  
Supercells, lightning, dark cloudscapes.

**C23 n=176 cohesion=0.642** — Cats being weird  
Arched backs, cats with drawn-on makeup, optical illusions, panda-painted crocodiles. Absurdist animal content.

**C06 n=132 cohesion=0.616** — Exotic animals held by humans  
Giant snails, bearded dragons, white snakes, opossums. Hands-on with unusual creatures.

**C22 n=108 cohesion=0.616** — Phone screenshots  
App homescreens, Google Photos UI, streaming platform interfaces.

**C10 n=127 cohesion=0.619** — Law enforcement / formal government  
Suits, salutes, press briefings, people being escorted. Not memes — actual event photography.

**C12 n=148 cohesion=0.610** — Craft / object photography  
Damascus steel, antique locks, marbled surfaces, mechanical sculptures. Artisanal objects.

**C29 n=141 cohesion=0.601** — Technical / code screenshots  
Stack Overflow, spreadsheets, rune tables, sheet music. Work and reference material.

**C00 n=103 cohesion=0.600** — Mueller / Russia investigation  
Mueller, Cohen, House Oversight testimony. Specific news event cluster.

**C08 n=110 cohesion=0.590** — Beach / bedroom lingerie  
More lifestyle than explicit. Third NSFW-adjacent cluster, most ambient.

**C25 n=68 cohesion=0.581** — Text message screenshots  
Conversations with Julian, Molly, Charlotte. Personal communications archived as photos.

**C49 n=98 cohesion=0.598** — Women in everyday settings  
Balconies, striped shirts, warmly lit rooms. Most casual / least stylized of the women clusters.

---

### Medium cohesion (0.50–0.65) — real but diffuse

**C40 n=168 cohesion=0.591** — Urban and dramatic environments  
Alleys, open-pit mines, warehouses, aerial roads. Landscape/architecture.

**C15 n=98 cohesion=0.564** — Film sets and formal events  
Directors, crew, tuxedos, gala settings.

**C36 n=312 cohesion=0.561** — Memes and internet humor  
Grumpy Cat, Clippy, absurdist jokes. Largest meme cluster.

**C26 n=114 cohesion=0.542** — Financial documents  
Credit reports, Amazon tracking, payment histories, cinema seat maps.

**C30 n=61 cohesion=0.553** — Infographics and data viz  
Pie charts, maps, network diagrams, population graphics.

**C18 n=205 cohesion=0.571** — Street art and sculpture  
Costumed performers, geometric metal structures, disturbing doll sculptures.

**C47 n=169 cohesion=0.520** — Viral / weird news  
Tableid headlines, heartwarming animal stories, bizarre human interest.

**C48 n=176 cohesion=0.518** — Political memes  
Stefan Molyneux, Trump Tower fire, far-right meme content.

**C45 n=150 cohesion=0.514** — Historical imagery  
WWI/WWII, zeppelins, crowds on ships, firefighters. Pre-digital era photos and reproductions.

**C17 n=114 cohesion=0.526** — Illustrated books and comics  
Ramayana, race car illustrations, grotesque figures. Physical book/print imagery.

**C27 n=116 cohesion=0.487** — Streaming content  
Netflix UI, Wikipedia show pages, movie posters. Content discovery screenshots.

**C21 n=159 cohesion=0.455** — Broader politics / protest  
BLM signs, Hillary Clinton, speeches, emotional political moments.

**C11 n=107 cohesion=0.450** — Long-form text screenshots  
Reddit posts, Wikipedia articles, medication lists. Reading material archived as photos.

**C42 n=164 cohesion=0.422** — Vintage oddities and product humor  
Cough syrup labels, LEGO parody, emergency underpants. Absurdist product/vintage content.

**C44 n=85 cohesion=0.389** — Three.js / WebGL / programming  
Your own work. Stack Overflow questions about SMAA, Three.js particles, regex.

---

## Key Observations

1. **Six distinct clusters of women**, differentiated by context: red carpet (C14, C09), candid/intimate (C13), editorial/outdoor (C46), casual/sporty (C38), everyday (C49), theatrical (C39). CLIP carves these apart more finely than conscious human categorization.

2. **Three NSFW clusters** at different levels of explicitness: C03 (explicit), C39 (theatrical/provocative), C08 (ambient/lifestyle).

3. **Personal clusters are the tightest**: prescription bottles (C19, 0.921), your cats (C04, 0.807), your chess games (C43, 0.626), your Three.js work (C44, 0.389 — loose because code screenshots vary). The most visually unique-to-you content is also most coherent.

4. **Nature splits cleanly**: underwater (C16) vs. land wildlife (C34) vs. dogs (C28) vs. cats-being-weird (C23) vs. exotic-animals-held (C06). Five animal clusters total.

5. **Politics splits**: Trump specifically (C31) vs. Mueller/Russia (C00) vs. law enforcement (C10) vs. political memes (C48) vs. broad politics/protest (C21). Heavy political consumption 2016–2019.

6. **Heavy internet archiving**: screenshots dominate — text messages (C25), financial docs (C26), infographics (C30), code/Stack Overflow (C29), phone UIs (C22), streaming UIs (C27), long-form text (C11). You used your camera as a clipboard.

7. **The Lying Bastard from Ringworld is in C33.** Make of that what you will.

---

## Next Steps (if revisiting)

- Push cluster labels into op.db for scatter view coloring
- Try k=80-100 to further split the large diffuse clusters (C36 memes, C18 street art, C48 political memes)
- Subcluster C36 (312 photos) — probably contains distinct meme formats
- Identify outliers: photos with low similarity to any centroid
- Semantic compass: use cluster centroids as directional anchors in Poincaré view
- The prescription bottle cluster (C19) is worth examining in detail — what's the story there?

---

## Repro Script

```python
import sqlite3, numpy as np
from sklearn.preprocessing import normalize
from sklearn.cluster import KMeans

con = sqlite3.connect('~/claude/open-photo/op.db')
cur = con.cursor()
rows = cur.execute('SELECT id, clip_embedding, caption FROM media WHERE clip_embedding IS NOT NULL').fetchall()
ids = [r[0] for r in rows]
captions = {r[0]: r[2] for r in rows}
embs = np.array([np.frombuffer(r[1], dtype=np.float32) for r in rows])
embs_n = normalize(embs)

km = KMeans(n_clusters=50, random_state=42, n_init=5).fit(embs_n)
labels = km.labels_
# labels[i] = cluster index for ids[i]
```
