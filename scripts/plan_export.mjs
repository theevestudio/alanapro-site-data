// Turn a monthly film-day planner page (claude.ai artifact HTML) + its saved picks
// into the read-only plan clients see in their portal.
// Usage: node scripts/plan_export.mjs <planner.html> <picks-dir> > plan.json
//   picks-dir holds one <slotId>.json per pick ({"version":"B"}), as ArtifactData list out_dir writes them.
// Keeps: dates, post type, theme, every version (A/B/C…) with title/kicker, end card, hook, script / what happens, photo,
// and which version is picked. Leaves out internal stuff: notes, shot lists, example links, the film-day list.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const [htmlPath, picksDir] = process.argv.slice(2);
const html = fs.readFileSync(htmlPath, "utf8");
const title = (html.match(/<title>([^<]*)<\/title>/g) || []).map(t => t.replace(/<\/?title>/g, "")).pop() || "";
const eyebrow = (html.match(/class="eyebrow">([^<]*)</) || [])[1] || "";
const lede = (html.match(/class="lede">([^<]*)</) || [])[1] || "";
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const src = scripts.find(s => s.includes("const SLOTS")) || "";
const head = src.split("/* ---------- state")[0];
const ctx = {};
vm.createContext(ctx);
vm.runInContext(head + "\n;globalThis.__out={S:typeof S!=='undefined'?S:{},TYPE:typeof TYPE!=='undefined'?TYPE:{},WEEKS,SLOTS};", ctx);
const { TYPE, WEEKS, SLOTS } = ctx.__out;

const picks = {};
if (picksDir && fs.existsSync(picksDir)) {
  for (const f of fs.readdirSync(picksDir)) if (f.endsWith(".json")) {
    try { picks[f.replace(/\.json$/, "")] = JSON.parse(fs.readFileSync(path.join(picksDir, f), "utf8")).version || ""; } catch {}
  }
}
const decode = s => String(s ?? "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
const endName = (src.match(/End card: \$\{esc\(v\.end\)\} · ([^<]*)</) || [])[1] || "";

const out = {
  v: 1, title: decode(title), eyebrow: decode(eyebrow), intro: "",
  endName: decode(endName),
  weeks: WEEKS.map(w => ({
    n: w.n, name: w.name, note: w.note,
    slots: SLOTS.filter(s => s.week === w.n).map(s => {
      const picked = s.v.find(v => v.k === picks[s.id]);
      const ver = v => {
        const kind = v.fmt || s.kind, isStatic = kind === "ST";
        const o = { k: v.k, name: v.name, isStatic, label: isStatic ? "Static post" : "Reel · " + ((TYPE[kind] || [kind])[0]) };
        if (isStatic) o.photo = v.shot;
        else Object.assign(o, { kicker: v.kicker, title: v.title, end: v.end, hook: v.hook, say: v.say, talk: kind === "TH" });
        return o;
      };
      return { id: s.id, date: s.date, day: s.day, theme: s.theme, pick: picked ? picked.k : null, versions: s.v.map(ver) };
    })
  }))
};
out.total = out.weeks.reduce((n, w) => n + w.slots.length, 0);
out.pickedCount = out.weeks.reduce((n, w) => n + w.slots.filter(s => s.pick).length, 0);
process.stdout.write(JSON.stringify(out));
