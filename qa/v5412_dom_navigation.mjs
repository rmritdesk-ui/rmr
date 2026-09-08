import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const root = path.resolve(process.argv[2] || '.');

class FakeControl {
  constructor(route, kind='route') {
    this.dataset = kind === 'v53' ? {v53Route: route} : {route};
    this.disabled = false;
    this.parentElement = null;
  }
  closest(selector) {
    return selector === '[data-route],[data-v53-route]' ? this : null;
  }
  getAttribute(name) { return name === 'aria-disabled' ? null : null; }
}

class FakeRoot {
  constructor() { this.listeners = new Map(); this._rmrRouteDelegate = null; }
  addEventListener(type, fn, capture) { this.listeners.set(`${type}:${capture}`, fn); }
  removeEventListener(type, fn, capture) {
    const key = `${type}:${capture}`;
    if (this.listeners.get(key) === fn) this.listeners.delete(key);
  }
  contains(control) { return control instanceof FakeControl; }
  dispatch(control) {
    const fn = this.listeners.get('click:true');
    if (!fn) throw new Error('Capture-phase route delegate not installed');
    const event = {
      target: control,
      prevented: false,
      stopped: false,
      preventDefault() { this.prevented = true; },
      stopImmediatePropagation() { this.stopped = true; }
    };
    fn(event);
    return event;
  }
}

const appRoot = new FakeRoot();
globalThis.document = {
  querySelector(selector) { return selector === '#app' ? appRoot : null; },
  querySelectorAll() { return []; }
};
globalThis.window = {matchMedia: () => ({matches:false})};
globalThis.localStorage = {getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
globalThis.sessionStorage = {getItem:()=>null,setItem:()=>{},removeItem:()=>{}};

const ui = await import(pathToFileURL(path.join(root, 'public/ui.js')).href + `?v=${Date.now()}`);
const routes = [];
ui.bindRouteDelegation(route => routes.push(route));
const expectedRoutes = ['website','crm','piq','campaigns','email','forecast'];
const events = expectedRoutes.map(route => appRoot.dispatch(new FakeControl(route)));
const v53Event = appRoot.dispatch(new FakeControl('reports?view=management', 'v53'));
const disabled = new FakeControl('solutions'); disabled.disabled = true;
appRoot.dispatch(disabled);

const expected = [...expectedRoutes, 'reports?view=management'];
if (JSON.stringify(routes) !== JSON.stringify(expected)) {
  throw new Error(`Unexpected delegated routes: ${JSON.stringify(routes)}`);
}
if (events.some(event => !event.prevented || !event.stopped) || !v53Event.prevented || !v53Event.stopped) {
  throw new Error('Delegated route click did not own navigation');
}

const unifiedSource = fs.readFileSync(path.join(root, 'public/pages/unified.js'), 'utf8');
if (!unifiedSource.includes("['forecast','training','organization','solutions'].includes(route)")) {
  throw new Error('Operational fallback list missing');
}
if (!unifiedSource.includes('ctx.renderClientOperational(route, readOnly)')) {
  throw new Error('Operational fallback renderer missing');
}

console.log(JSON.stringify({
  status: 'passed',
  route_delegate: routes,
  forecast_fallback: ['forecast','training','organization','solutions']
}, null, 2));
