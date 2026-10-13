// Approved shared vector geometry. No independently redrawn brand paths.
import brand from '../assets/seatpal/brand.json';
type Node={tag:string;attrs:Record<string,string|number|undefined>;children:Node[]};
const escape=(value:string|number)=>String(value).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
function xml(node:Node):string{
 const attrs=Object.entries(node.attrs).filter(([key,value])=>value!==undefined&&key!=='class'&&!key.startsWith('data-')).map(([key,value])=>`${key}="${escape(value!)}"`).join(' ');
 return `<${node.tag} ${attrs}>${node.children.map(xml).join('')}</${node.tag}>`;
}
const svg=(viewBox:string,nodes:Node[])=>`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}">${nodes.map(xml).join('')}</svg>`;
const seat=brand.hero.seat as Node,back=seat.children[0];
export const seatPalColors=brand.colors;
export const seatPalArt={mark:svg(brand.mark.viewBox,brand.mark.nodes),car:svg(brand.hero.viewBox,[brand.hero.car]),motorcycle:svg(brand.hero.viewBox,[brand.hero.motorcycle]),backrest:svg(brand.hero.viewBox,[back.children[1]]),headrest:svg(brand.hero.viewBox,[back.children[0]]),base:svg(brand.hero.viewBox,[seat.children[1]]),cushion:svg(brand.hero.viewBox,[seat.children[2]])};
