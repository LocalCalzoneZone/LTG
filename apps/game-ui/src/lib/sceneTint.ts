import { useEffect, useState } from "react";

// Scene-aware ambience: sample the backdrop's dominant colour once per image
// and hand it to the mote layer, so the dust matches the light — embers in a
// fire scene, spores in a grove. Blended halfway back toward brass so the
// ambience never leaves the house palette.

const BRASS = { r: 233, g: 204, b: 130 };
const cache = new Map<string, string>();

function sample(url: string): Promise<string> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      try {
        const w = 24;
        const h = 24;
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("no 2d context");
        ctx.drawImage(img, 0, 0, w, h);
        const px = ctx.getImageData(0, 0, w, h).data;
        // Average the SATURATED, non-dark pixels — the scene's light, not its
        // shadows; fall back to brass when the scene is near-monochrome.
        let r = 0, g = 0, b = 0, n = 0;
        for (let i = 0; i < px.length; i += 4) {
          const [pr, pg, pb] = [px[i], px[i + 1], px[i + 2]];
          const max = Math.max(pr, pg, pb);
          const sat = max - Math.min(pr, pg, pb);
          if (max > 70 && sat > 24) { r += pr; g += pg; b += pb; n += 1; }
        }
        if (n < 12) { resolve(""); return; }
        const mix = (v: number, target: number) => Math.round(v / n * 0.5 + target * 0.5);
        resolve(`rgb(${mix(r, BRASS.r)}, ${mix(g, BRASS.g)}, ${mix(b, BRASS.b)})`);
      } catch {
        resolve(""); // tainted canvas or draw failure — keep the brass default
      }
    };
    img.onerror = () => resolve("");
    img.src = url;
  });
}

/** The mote tint for a scene image URL, "" until sampled (brass default). */
export function useSceneTint(url: string | null | undefined): string {
  const [tint, setTint] = useState("");
  useEffect(() => {
    if (!url) { setTint(""); return; }
    const hit = cache.get(url);
    if (hit != null) { setTint(hit); return; }
    let live = true;
    sample(url).then((c) => {
      cache.set(url, c);
      if (live) setTint(c);
    });
    return () => { live = false; };
  }, [url]);
  return tint;
}
