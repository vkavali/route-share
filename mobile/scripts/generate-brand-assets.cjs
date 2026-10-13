#!/usr/bin/env node
/* Deterministic SeatPal assets. Source: static/assets/seatpal/brand.json. */
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '../..');
const check = process.argv.includes('--check');
let sharp;
try { sharp = require(process.env.SEATPAL_SHARP_MODULE || 'sharp'); }
catch { throw new Error('Use the existing Sharp runtime: set SEATPAL_SHARP_MODULE to its installed module path. No download is performed.'); }
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const sourcePath = 'static/assets/seatpal/brand.json';
const outputs = new Map();
function serialize(node) {
  const attrs = Object.entries(node.attrs || {}).filter(([key]) => key !== 'class' && !key.startsWith('data-')).map(([key,value]) => ` ${key}="${escape(value)}"`).join('');
  return `<${node.tag}${attrs}>${(node.children || []).map(serialize).join('')}</${node.tag}>`;
}
function svg(viewBox, nodes) { return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}">${nodes.map(serialize).join('')}</svg>\n`; }
function recolor(node, color) {
  const copy = structuredClone(node);
  if (copy.attrs?.fill && copy.attrs.fill !== 'none') copy.attrs.fill = color;
  copy.children = (copy.children || []).map(child => recolor(child, color));
  return copy;
}
function posedSeat(hero, pose) {
  const seat = structuredClone(hero.seat);
  const visit = node => {
    if ('data-seat-back' in node.attrs && pose.backrest) node.attrs.transform = pose.backrest;
    if ('data-seat-base' in node.attrs && pose.base) node.attrs.transform = pose.base;
    if ('data-seat-headrest' in node.attrs) node.attrs.opacity = String(pose.headrestOpacity);
    for (const child of node.children || []) visit(child);
  };
  visit(seat); return seat;
}
// Startup renders before application scripts: keep its inline nodes canonical too.
function assertInlineHero(html, brand) {
  const start = '<!-- seatpal:canonical-hero:start -->';
  const end = '<!-- seatpal:canonical-hero:end -->';
  if (html.split(start).length !== 2 || html.split(end).length !== 2) {
    throw new Error('static/index.html must contain one seatpal:canonical-hero marker pair.');
  }
  const startIndex = html.indexOf(start) + start.length;
  const endIndex = html.indexOf(end);
  const region = html.slice(startIndex, endIndex).trim();
  const match = region.match(/^<svg\b([^>]*)>([\s\S]*)<\/svg>$/);
  if (endIndex < startIndex || !match || !match[1].includes(`viewBox="${brand.hero.viewBox}"`)) {
    throw new Error('Startup SeatPal SVG wrapper/viewBox differs from canonical brand.json.');
  }
  const canonical = node => `<${node.tag}${Object.entries(node.attrs || {}).map(([key,value]) => ` ${key}="${escape(value)}"`).join('')}>${(node.children || []).map(canonical).join('')}</${node.tag}>`;
  const normalize = value => value.trim().replace(/>\s+</g, '><');
  const expected = [brand.hero.car, brand.hero.motorcycle, brand.hero.seat].map(canonical).join('');
  if (normalize(match[2]) !== normalize(expected)) {
    throw new Error('Startup SeatPal inline geometry/fills/motion hooks are stale. Regenerate the marked SVG from brand.json.hero car, motorcycle and seat; do not redraw paths.');
  }
}
async function png(svgText, width, opaque) {
  let image = sharp(Buffer.from(svgText)).resize(width,width);
  if (opaque) image = image.flatten({background:opaque}).removeAlpha();
  return image.png({compressionLevel:9,adaptiveFiltering:false,palette:false}).toBuffer();
}
function framed(mark, size, inset, background) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${background ? `<rect width="${size}" height="${size}" fill="${background}"/>` : ''}<g transform="translate(${inset} ${inset}) scale(${(size-inset*2)/64})">${mark.map(serialize).join('')}</g></svg>`;
}
(async()=>{
  const bytes = await fs.readFile(path.join(root,sourcePath));
  const brand = JSON.parse(bytes);
  if (check) assertInlineHero(await fs.readFile(path.join(root, 'static/index.html'), 'utf8'), brand);
  const seat = svg(brand.mark.viewBox,brand.mark.nodes);
  const mono = svg(brand.mark.viewBox,brand.mark.nodes.map(n=>recolor(n,brand.colors.forest)));
  const web = 'static/assets/seatpal/';
  const native = 'mobile/assets/seatpal/';
  const vectors = {
    'seat.svg':seat,
    'seat-mono.svg':mono,
    'core.svg':svg(brand.hero.viewBox,[brand.hero.seat]),
    'car.svg':svg(brand.hero.viewBox,[brand.hero.car,posedSeat(brand.hero,brand.hero.poses.car)]),
    'motorcycle.svg':svg(brand.hero.viewBox,[brand.hero.motorcycle,posedSeat(brand.hero,brand.hero.poses.motorcycle)])
  };
  for(const [name,value] of Object.entries(vectors)) { outputs.set(web+name,Buffer.from(value)); outputs.set(native+name,Buffer.from(value)); }
  outputs.set('static/icon.svg',Buffer.from(seat));
  outputs.set(native+'brand.json',bytes);
  outputs.set(native+'icon-ios.png',await png(framed(brand.mark.nodes,1024,96,brand.colors.ivory),1024,brand.colors.ivory));
  outputs.set(native+'adaptive-foreground.png',await png(framed(brand.mark.nodes,1024,224),1024));
  outputs.set(native+'adaptive-monochrome.png',await png(framed(brand.mark.nodes.map(n=>recolor(n,'#FFFFFF')),1024,224),1024));
  outputs.set(native+'splash.png',await png(seat,1200));
  outputs.set(native+'mark.png',await png(seat,256));
  const files=[];
  for(const [name,data] of outputs) {
    const item={path:name,bytes:data.length,sha256:hash(data)};
    if(name.endsWith('.png')){
      const meta=await sharp(data).metadata();const {data:raw,info}=await sharp(data).ensureAlpha().raw().toBuffer({resolveWithObject:true});
      let x0=info.width,y0=info.height,x1=-1,y1=-1,transparent=0;
      for(let y=0;y<info.height;y++)for(let x=0;x<info.width;x++){
        const a=raw[(y*info.width+x)*4+3];if(!a)transparent++;
        if(a){x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);}
      }
      Object.assign(item,{width:meta.width,height:meta.height,channels:meta.channels,hasAlpha:meta.hasAlpha,alphaBounds:[x0,y0,x1+1,y1+1],transparentPixels:transparent});
      if(name.includes('icon-ios')&&(meta.hasAlpha||meta.width!==1024))throw Error('Opaque iOS icon invariant failed');
      if(name.includes('adaptive-')&&(x0<170||y0<170||x1>=854||y1>=854))throw Error('Adaptive safe-zone invariant failed');
    }
    files.push(item);
  }
  const manifest={version:1,source:sourcePath,sourceSha256:hash(bytes),approvedSource:brand.source,colors:brand.colors,generator:'mobile/scripts/generate-brand-assets.cjs',renderer:{sharp:sharp.versions.sharp,vips:sharp.versions.vips},nativeHandoff:{splashAndMarkSameViewBox:true,splashImageWidthRecommended:120,adaptiveBackground:brand.colors.ivory,iosOpaque:true},files};
  outputs.set(web+'manifest.json',Buffer.from(JSON.stringify(manifest,null,2)+'\n'));
  for(const [name,data] of outputs){
    const file=path.join(root,name);
    if(check){const actual=await fs.readFile(file);if(!actual.equals(data))throw Error(`Generated brand asset is stale: ${name}`);}
    else {await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,data);}
  }
  console.log(JSON.stringify({mode:check?'check':'generate',inlineStartupCanonical:check,files:outputs.size,sourceSha256:hash(bytes),png:files.filter(x=>x.path.endsWith('.png'))},null,2));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
