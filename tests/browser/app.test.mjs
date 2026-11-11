// Browser tests for index.html: runs the ?mock demo in headless Chrome and checks every plan it makes.
// No packages: Node's built in test runner and WebSocket talk to Chrome over the DevTools protocol.
// Run: node --test tests/browser/app.test.mjs   (CHROME=/path/to/chrome if it isn't found on its own)
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as sleep } from "node:timers/promises";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const CHROME = process.env.CHROME || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"].find(existsSync);
const PORT = 8700 + Math.floor(Math.random() * 200), DEBUG = PORT + 300;
const LIMIT_KM = { walk: 1.25, transit: 6, car: 10 }, MODE = { walk: "walking", transit: "transit", car: "driving" };
let server, chrome, ws, session, profile, msgId = 0;
const waiting = new Map(), pageErrors = [];

function send(method, params = {}, sessionId = session) {
  return new Promise((resolve, reject) => {
    const id = ++msgId;
    waiting.set(id, m => m.error ? reject(new Error(`${method}: ${m.error.message}`)) : resolve(m.result));
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
}
async function page(expr) {  // evaluate in the app, awaiting promises
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
}
async function until(expr, seconds = 90) {
  for (let i = 0; i < seconds * 4; i++) { if (await page(expr)) return; await sleep(250); }
  throw new Error(`timed out waiting for ${expr}`);
}
async function open(setup = true) {
  await send("Page.navigate", { url: `http://127.0.0.1:${PORT}/index.html?mock` });
  await until(`typeof CITY!=="undefined"&&!!CITY&&!!document.querySelector("#cityChips .chip")`, 30);
  if (setup) await page(`store.set("onboarded",1);$("onboard").classList.add("hide");$("setup").classList.remove("hide")`);
}
const chip = name => page(`(async()=>{const b=[...$("cityChips").children].find(b=>b.textContent===${JSON.stringify(name)});b.click();await new Promise(r=>setTimeout(r,300))})()`);
async function city(name) { await chip(name); await until(`CITY.name===${JSON.stringify(name)}&&SPOTS.length>0`, 30); }
async function runDemo(move) {
  await page(`(()=>{plan.move="${move}";plan.hood="Anywhere";savePlan();$("newBtn").click()})()`);
  await page(`$("startBtn").click()`);
  await until(`!!lastPlan&&!busy&&!!document.querySelector("#chat .ticket")`);
  return inspect();
}
// what the app itself thinks of the plan on screen: types, shortlist, open hours, distances, route mode
const inspect = () => page(`(()=>{const p=lastPlan,base=nightDate(p.when||plan.when);
  return {move:plan.move,mode:new URL(routeUrl(p.stops)).searchParams.get("travelmode"),
    stops:p.stops.map(s=>{const t=parseTime(s.time,base),m=t.getHours()*60+t.getMinutes()+(t.getDate()!==base.getDate()?1440:0);
      return {n:s.spot.n,t:s.spot.t,time:s.time,onList:SL.list.includes(s.spot),shut:shut(s.spot,t,m)}}),
    legs:p.stops.slice(1).map((s,i)=>km(p.stops[i].spot,s.spot))}})()`);
function assertValid(plan, label) {
  const names = plan.stops.map(s => `${s.time} ${s.n} [${s.t}]`).join(", ");
  // 3 stops, or 2 when nothing open was within reach for the late stop (the planner ends the night after drinks)
  assert.ok(plan.stops.length === 3 || plan.stops.length === 2, `${label}: 2 or 3 stops (${names})`);
  assert.deepEqual(plan.stops.map(s => s.t === "free" ? "late" : s.t), ["dinner", "drinks", "late"].slice(0, plan.stops.length), `${label}: dinner, drinks, late (${names})`);
  for (const s of plan.stops) {
    assert.ok(s.onList, `${label}: ${s.n} is on the shortlist`);
    assert.ok(!s.shut, `${label}: ${s.n} is open at ${s.time}`);
  }
  plan.legs.forEach((d, i) => assert.ok(d == null || d <= LIMIT_KM[plan.move], `${label}: leg ${i + 1} is ${d?.toFixed(2)} km, limit ${LIMIT_KM[plan.move]} (${names})`));
  assert.equal(plan.mode, MODE[plan.move], `${label}: route opens in ${MODE[plan.move]} mode`);
}

before(async () => {
  assert.ok(CHROME, "Chrome not found: set CHROME=/path/to/chrome");
  server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1", "--directory", ROOT], { stdio: "ignore" });
  profile = mkdtempSync(join(tmpdir(), "pc-browser-"));
  // --no-sandbox only in CI, where Ubuntu blocks Chrome's sandbox; the page is our own local copy
  chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${DEBUG}`, `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", ...(process.env.CI ? ["--no-sandbox"] : []), "about:blank"], { stdio: "ignore" });
  let url;
  for (let i = 0; i < 100 && !url; i++) {
    try { url = (await (await fetch(`http://127.0.0.1:${DEBUG}/json/version`)).json()).webSocketDebuggerUrl; } catch { await sleep(200); }
  }
  assert.ok(url, "Chrome did not start");
  ws = new WebSocket(url);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
    else if (m.method === "Runtime.exceptionThrown") pageErrors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  };
  const { targetId } = await send("Target.createTarget", { url: "about:blank" }, undefined);
  session = (await send("Target.attachToTarget", { targetId, flatten: true }, undefined)).sessionId;
  await send("Runtime.enable");
  await send("Emulation.setTimezoneOverride", { timezoneId: "America/New_York" });
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  for (let i = 0; i < 50; i++) { try { await fetch(`http://127.0.0.1:${PORT}/index.html`); break; } catch { await sleep(200); } }
  await open();
});

after(() => {
  ws?.close(); chrome?.kill(); server?.kill();
  if (profile) try { rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* Chrome may still be writing its profile */ }
});

test("demo plans are valid in every city and travel mode", async () => {
  for (const name of ["New York City", "London"]) {
    await city(name);
    for (const move of ["walk", "transit", "car"]) assertValid(await runDemo(move), `${name}, ${move}`);
  }
});

test("guardrails fix a bad plan from the AI", async () => {
  await city("New York City");
  await page(`(()=>{plan.move="walk";plan.when="Saturday night";plan.start=1140;plan.hood="Anywhere";SL=shortlist()})()`);
  // a dinner place in the drinks slot, a drinks place as the late stop, and a place that isn't on the shortlist
  const bad = await page(`(()=>{const of=t=>SL.list.find(s=>s.t===t).n,off=SPOTS.find(s=>!SL.list.includes(s)&&s.t==="dinner").n;
    return [[{time:"7 pm",name:of("dinner")},{time:"9 pm",name:of("dinner")},{time:"10:30 pm",name:of("drinks")}],
            [{time:"7 pm",name:off},{time:"9 pm",name:of("drinks")},{time:"10:30 pm",name:of("late")}],
            [{time:"7 pm",name:of("dinner")},{time:"9 pm",name:of("drinks")},{time:"10:30 pm",name:SPOTS.filter(s=>s.t==="late").sort((x,y)=>km(SL.list.find(s=>s.t==="drinks"),y)-km(SL.list.find(s=>s.t==="drinks"),x))[0].n}]]})()`);  // the late stop as far away as the city allows
  for (const stops of bad) {
    await page(`(async()=>{const keep=llm;llm=async()=>({text:JSON.stringify({title:"t",drama:50,verdict:"v",stops:${JSON.stringify(stops)}})});
      try{lastPlan=await makePlan()}finally{llm=keep}})()`);
    const p = await inspect();
    assert.deepEqual(p.stops.map(s => s.t === "free" ? "late" : s.t), ["dinner", "drinks", "late"].slice(0, p.stops.length), `swapped into the right types: ${p.stops.map(s => s.n).join(", ")}`);
    assert.ok(p.stops.every(s => s.onList), "every stop is on the shortlist");
    p.legs.forEach((d, i) => assert.ok(d == null || d <= LIMIT_KM.walk, `leg ${i + 1} is walkable: ${d?.toFixed(2)} km (${p.stops.map(s => s.n).join(", ")})`));
    assert.ok(p.stops.length >= 2, "never less than dinner and drinks");
  }
});

test("early closers and places about to close stay out late", async () => {
  const r = await page(`(()=>{const d=nightDate("Saturday night"),spot=(n,v,t="late",hrs)=>({n,v,t,hrs,cur:false,f:[],x:[]});
    const closes11=Array.from({length:7},()=>[[600,1380]]);
    return {museumLate:shut(spot("City Museum",""),d,1350),museumEarly:shut(spot("City Museum",""),d,1140),
      theatreLate:shut(spot("Segal Center","CUNY theatre center"),d,1350),templeBar:shut(spot("Temple Bar","cocktail bar"),d,1350),
      halfHourLeft:shut(spot("Little Park","","free",closes11),d,1350),twoHoursLeft:shut(spot("Little Park","","free",closes11),d,1260)}})()`);
  assert.equal(r.museumLate, true, "a museum with unknown hours is out at 10:30 pm");
  assert.equal(r.museumEarly, false, "the same museum is fine at 7 pm");
  assert.equal(r.theatreLate, true, "a theatre with unknown hours is out at 10:30 pm");
  assert.equal(r.templeBar, false, "a bar named like a temple is still fine late");
  assert.equal(r.halfHourLeft, true, "a place closing in 30 minutes is out");
  assert.equal(r.twoHoursLeft, false, "a place with 2 hours left is fine");
});

test("switching city clears the notice, and a typed city loads on Start", async () => {
  await city("New York City");
  await page(`say("710 places around Paris, from OpenStreetMap.")`);
  await city("London");
  assert.equal(await page(`$("notice").style.display`), "none", "notice hidden after switching city");
  assert.equal(await page(`$("notice").textContent`), "", "notice cleared");
  // typed under Somewhere else, then Start without Find: a city pack, so no network lookup is needed
  await page(`(()=>{$("newBtn").click();$("geoRow").style.display="";$("geoInput").value="New York";$("startBtn").click()})()`);
  await until(`!!lastPlan&&!busy&&!!document.querySelector("#chat .ticket")`);
  assert.equal(await page(`CITY.id`), "nyc", "the typed city is the one that ran");
});

test("adding a person opens their picks straight away", async () => {
  await page(`(()=>{$("newBtn").click();plan.members=plan.members.filter(m=>m.n!=="Sam");savePlan();renderSetup();$("quickName").value="Sam";$("addForm").requestSubmit()})()`);
  await until(`!$("quiz").classList.contains("hide")`, 5);
  assert.equal(await page(`$("qzQ").textContent`), "How does Sam argue about plans?");
  await page(`$("closeQuiz").click()`);
  assert.equal(await page(`$("quiz").classList.contains("hide")`), true, "the close button works");
});

test("the last chat and plan survive a reload", async () => {
  await city("London");
  const before = (await runDemo("walk")).stops.map(s => s.n);
  await open(false);  // a plain reload
  await until(`!!document.querySelector("#chat .ticket")`, 15).catch(async e => {
    throw new Error(`${e.message}: ${await page(`JSON.stringify((L=>({saved:!!L,crew:L?.crew===plan.id,city:L?.city+" vs "+CITY.id,agents:L?.agents?.map(a=>a.n).join()+" vs "+agentList().map(a=>a.n).join(),age:L&&Date.now()-L.at,setup:!$("setup").classList.contains("hide")}))(store.get("last",null)))`)}`);
  });
  assert.deepEqual(await page(`lastPlan.stops.map(s=>s.spot.n)`), before, "same plan after reload");
  assert.equal(await page(`$("setup").classList.contains("hide")`), true, "lands on the chat, not setup");
});

test("no errors on the page", () => {
  assert.deepEqual(pageErrors, []);
});
