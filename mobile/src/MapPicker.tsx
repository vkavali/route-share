import {SeatPalLoader} from './SeatPalLoader';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import { Keyboard, Linking, Pressable, ScrollView, StyleSheet, TextInput, View} from 'react-native';
import {WebView, WebViewMessageEvent} from 'react-native-webview';
import * as Location from 'expo-location';
import {Api, Point} from './api';
import {LEAFLET_CSS, LEAFLET_JS} from './generated/leaflet';
import {T} from './translation';
import {AppText} from './NativeTypography';
import {normalizePlace, PlaceCandidate, SelectionIntent, samePlace} from './placeSelection';
import {SeatPalTheme} from './SeatPalTheme';

type Props = {lang:string; api:Api; initialPoint?:Point|null; initialQuery?:string; title?:string;
 onChoose:(p:Point)=>void; onCancel:()=>void; onFailure:(error:unknown)=>void};

export function MapPicker({lang,api,initialPoint,initialQuery='',title,onChoose,onCancel,onFailure}:Props) {
 const initial=initialQuery.trim()?null:normalizePlace(initialPoint);
 const web=useRef<WebView>(null), ready=useRef(false), intent=useRef(new SelectionIntent());
 const mounted=useRef(true), pointRef=useRef<PlaceCandidate|null>(initial);
 const queryRef=useRef(initialQuery), operation=useRef<'search'|'gps'|'reverse'|null>(null);
 const [query,setQuery]=useState(initialQuery), [results,setResults]=useState<PlaceCandidate[]>([]);
 const [candidate,setCandidate]=useState<PlaceCandidate|null>(initial), [error,setError]=useState('');
 const [busy,setBusy]=useState<'search'|'gps'|'reverse'|null>(null), [searched,setSearched]=useState(false);
 const [tilesError,setTilesError]=useState(false);
 const t=(key:string)=>T(lang,key);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;intent.current.next();};},[]);
 const current=(token:number)=>mounted.current&&intent.current.isCurrent(token);
 const replayPoint=()=>{if(!ready.current)return;const p=pointRef.current;
  web.current?.injectJavaScript(p?`window.setCandidate(${p.lat},${p.lon});true;`:'window.setCandidate(null,null);true;');};
 const setPoint=(p:PlaceCandidate|null,center=true)=>{pointRef.current=p;setCandidate(p);if(center)replayPoint();};
 const invalidate=()=>{intent.current.next();operation.current=null;setBusy(null);};
 const editQuery=(value:string)=>{invalidate();queryRef.current=value;setQuery(value);setResults([]);setSearched(false);setError('');setPoint(null);};
 const selectPoint=(p:PlaceCandidate,center=true)=>{invalidate();setError('');setPoint(p,center);Keyboard.dismiss();};
 const html=useMemo(()=>`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: https://tile.openstreetmap.org; connect-src https://tile.openstreetmap.org; font-src data:"><style>html,body,#map{height:100%;margin:0}.route-share-pin{background:transparent;border:0}.route-share-pin span{display:block;width:20px;height:20px;border:3px solid white;border-radius:50%;background:${SeatPalTheme.colors.primary};box-shadow:0 1px 5px ${SeatPalTheme.colors.scrim}}${LEAFLET_CSS}</style></head><body><div id="map"></div><script>${LEAFLET_JS}</script><script>const map=L.map('map').setView([17.2,79.3],8);const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>'}).addTo(map);let marker=null;function notify(ll){window.ReactNativeWebView.postMessage(JSON.stringify({type:'candidate',lat:ll.lat,lon:ll.lng}));}function pin(ll,send){if(marker){marker.setLatLng(ll);}else{marker=L.marker(ll,{draggable:true,icon:L.divIcon({className:'route-share-pin',html:'<span></span>',iconSize:[24,24],iconAnchor:[12,12]})}).addTo(map);marker.on('dragend',e=>notify(e.target.getLatLng()));}if(send)notify(ll);}map.on('click',e=>pin(e.latlng,true));window.setCandidate=(lat,lon)=>{if(lat===null||lon===null){if(marker){map.removeLayer(marker);marker=null;}return;}const ll=L.latLng(lat,lon);map.setView(ll,14);pin(ll,false);};tiles.on('tileerror',()=>window.ReactNativeWebView.postMessage(JSON.stringify({type:'tiles-error'})));tiles.on('load',()=>window.ReactNativeWebView.postMessage(JSON.stringify({type:'tiles-loaded'})));window.ReactNativeWebView.postMessage(JSON.stringify({type:'ready'}));</script></body></html>`,[]);
 const onMessage=(event:WebViewMessageEvent)=>{try{
  const raw=event.nativeEvent.data;if(typeof raw!=='string'||raw.length>512)return;
  const data=JSON.parse(raw);if(!data||typeof data!=='object')return;
  if(data.type==='ready'){ready.current=true;replayPoint();return;}
  if(data.type==='tiles-error'){setTilesError(true);return;}
  if(data.type==='tiles-loaded'){return;}
  if(data.type!=='candidate')return;
  const point=normalizePlace({lat:data.lat,lon:data.lon,label:t('mapSelectedPoint')});
  if(point){selectPoint(point,false);setResults([]);setSearched(false);}
 }catch{/* Ignore malformed messages from the embedded map. */}};
 const search=async()=>{
  if(operation.current==='search')return;
  const term=queryRef.current.trim();
  if(term.length<3||term.length>160){invalidate();setPoint(null);setResults([]);setError(t('mapSearchRequired'));return;}
  const token=intent.current.next();operation.current='search';setBusy('search');setError('');
  setPoint(null);setResults([]);setSearched(false);Keyboard.dismiss();
  try{const response=await api.request(`/api/places?q=${encodeURIComponent(term)}&lang=${encodeURIComponent(lang)}`);
   if(!current(token))return;
   const rows=Array.isArray(response.places)?response.places:[];
   setResults(rows.map(normalizePlace).filter((p:PlaceCandidate|null):p is PlaceCandidate=>p!==null).slice(0,6));setSearched(true);
  }catch(e){if(current(token)){setError(t('mapSearchError'));onFailure(e);}}
  finally{if(current(token)){operation.current=null;setBusy(null);}}
 };
 const useCurrent=async()=>{
  if(operation.current==='gps')return;
  const token=intent.current.next();operation.current='gps';setBusy('gps');setError('');
  setPoint(null);setResults([]);setSearched(false);Keyboard.dismiss();
  let timer:ReturnType<typeof setTimeout>|undefined;
  try{const permission=await Location.requestForegroundPermissionsAsync();if(!current(token))return;
   if(!permission.granted){setError(t('mapLocationDenied'));return;}
   const location=await Promise.race([Location.getCurrentPositionAsync({accuracy:Location.Accuracy.High}),
    new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error('location-timeout')),15000);})]);
   if(!current(token))return;
   const point=normalizePlace({lat:location.coords.latitude,lon:location.coords.longitude,label:t('mapCurrentLocation')});
   if(!point){setError(t('mapLocationError'));return;}setPoint(point);
  }catch(e){if(current(token))setError(t(e instanceof Error&&e.message==='location-timeout'?'mapLocationTimeout':'mapLocationError'));}
  finally{if(timer)clearTimeout(timer);if(current(token)){operation.current=null;setBusy(null);}}
 };
 const lookupAddress=async()=>{
  const point=pointRef.current;if(!point||operation.current==='reverse')return;
  const token=intent.current.next();operation.current='reverse';setBusy('reverse');setError('');
  try{const response=await api.request(`/api/places/reverse?lat=${point.lat}&lon=${point.lon}&lang=${encodeURIComponent(lang)}`);
   if(!current(token))return;
   const named=normalizePlace(response.place);
   if(named)setPoint({...named,lat:point.lat,lon:point.lon},false);
   else setError(t('mapAddressUnavailable'));
  }catch(e){if(current(token)){setError(t('mapAddressError'));onFailure(e);}}
  finally{if(current(token)){operation.current=null;setBusy(null);}}
 };
 const chooseResult=(point:PlaceCandidate)=>selectPoint(point);
 const cancel=()=>{invalidate();onCancel();};
 const confirm=()=>{const point=pointRef.current;if(point&&!operation.current){invalidate();onChoose({...point});}};
 const nav=({url,isTopFrame}:{url:string;isTopFrame?:boolean})=>{if(isTopFrame===false)return true;
  if(url==='about:blank'||url==='https://localhost'||url==='https://localhost/')return true;
  try{const target=new URL(url);if(target.origin==='https://www.openstreetmap.org'&&target.pathname==='/copyright'&&!target.search&&!target.hash)void Linking.openURL('https://www.openstreetmap.org/copyright');}catch{}
  return false;};
 return <View style={styles.wrap}>
  <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag">
   <AppText style={styles.title}>{title||t('mapPickTitle')}</AppText>
   <AppText style={styles.help}>{t('mapSearchHelp')}</AppText>
   <View style={styles.searchRow}>
    <TextInput accessibilityLabel={t('mapSearchLabel')} value={query} onChangeText={editQuery}
     onSubmitEditing={()=>void search()} returnKeyType="search" maxLength={160} autoCorrect={false}
     placeholder={t('mapSearchLabel')} placeholderTextColor={SeatPalTheme.colors.secondary}
     style={[styles.input,{fontFamily:lang==='te'?'AnekTelugu500':'Manrope500',lineHeight:lang==='te'?25:22}]}/>
    <Pressable accessibilityRole="button" disabled={busy==='search'} onPress={()=>void search()}
     accessibilityLabel={t('mapSearch')} style={[styles.search,busy==='search'&&styles.disabled]}>
     <AppText style={styles.searchText}>{t('mapSearch')}</AppText></Pressable>
   </View>
   <Pressable accessibilityRole="button" disabled={busy==='gps'} onPress={()=>void useCurrent()} style={styles.gps}>
    <AppText style={styles.gpsText}>{t('mapMyLocation')}</AppText></Pressable>
   {busy?<SeatPalLoader label={t(busy==='gps'?'mapLocationBusy':busy==='reverse'?'mapAddressLoading':'mapSearchLoading')}/>:null}
   {error?<AppText accessibilityRole="alert" style={styles.error}>{error}</AppText>:null}
   {searched&&!results.length&&!busy?<AppText accessibilityLiveRegion="polite" style={styles.help}>{t('mapSearchEmpty')}</AppText>:null}
   {results.length?<View style={styles.results}><AppText style={styles.resultsTitle}>{t('mapSearchResult')}</AppText>
    {results.map((point,index)=><Pressable key={point.id||`${point.lat}:${point.lon}:${index}`}
     accessibilityRole="button" accessibilityState={{selected:samePlace(candidate,point)}}
     onPress={()=>chooseResult(point)} style={[styles.result,samePlace(candidate,point)&&styles.resultSelected]}>
     <AppText style={styles.resultText}>{point.name||point.label}</AppText>
     {point.address&&point.address!==(point.name||point.label)?<AppText style={styles.address}>{point.address}</AppText>:null}
     {samePlace(candidate,point)?<AppText style={styles.selectionTag}>{t('mapSelectedPoint')}</AppText>:null}
    </Pressable>)}
   </View>:null}
   <AppText style={styles.help}>{t('mapRefineHint')}</AppText>
   <View style={styles.mapFrame}><WebView ref={web} source={{html,baseUrl:'https://localhost'}}
    originWhitelist={['about:blank','https://localhost']} javaScriptEnabled
    onLoadStart={()=>{ready.current=false;setTilesError(false);}}
    onLoadEnd={()=>{if(ready.current)replayPoint();}}
    onError={()=>setTilesError(true)} onMessage={onMessage} onShouldStartLoadWithRequest={nav}
    applicationNameForUserAgent="RouteShareLocalBeta/0.1" style={styles.map}/></View>
   {candidate&&!candidate.address?<Pressable accessibilityRole="button" disabled={busy==='reverse'} onPress={()=>void lookupAddress()} style={styles.gps}><AppText style={styles.gpsText}>{t('mapResolveAddress')}</AppText></Pressable>:null}
   {tilesError?<AppText accessibilityRole="alert" style={styles.error}>{t('mapTilesError')}</AppText>:null}
   <View style={styles.provider}><AppText style={styles.providerText}>{t('mapProviderNotice')}</AppText>
    <Pressable accessibilityRole="link" onPress={()=>void Linking.openURL('https://operations.osmfoundation.org/policies/nominatim/')}><AppText style={styles.policy}>{t('mapProviderPolicy')}</AppText></Pressable></View>
  </ScrollView>
  <View style={styles.footer}>
   <AppText numberOfLines={2} style={styles.selected}>{candidate?candidate.label:t('locationNotChosen')}</AppText>
   {candidate?.address&&candidate.address!==candidate.label?<AppText numberOfLines={2} style={styles.address}>{candidate.address}</AppText>:null}
   <View style={styles.buttons}>
    <Pressable accessibilityRole="button" onPress={cancel} style={styles.cancel}><AppText style={styles.cancelText}>{t('mapCancel')}</AppText></Pressable>
    <Pressable accessibilityRole="button" disabled={!candidate||Boolean(busy)} onPress={confirm}
     style={[styles.confirm,(!candidate||Boolean(busy))&&styles.disabled]}><AppText style={styles.confirmText}>{t('mapUsePoint')}</AppText></Pressable>
   </View>
  </View>
 </View>;
}
const styles=StyleSheet.create({
 wrap:{flex:1,backgroundColor:SeatPalTheme.colors.page},content:{padding:16,gap:12,paddingBottom:20},
 title:{fontSize:23,fontWeight:'700',color:SeatPalTheme.colors.text},help:{color:SeatPalTheme.colors.secondary,fontSize:14,lineHeight:22},
 searchRow:{flexDirection:'row',gap:8,alignItems:'stretch'},input:{flex:1,minWidth:0,minHeight:50,borderWidth:1,borderColor:SeatPalTheme.colors.border,borderRadius:12,paddingHorizontal:12,paddingVertical:10,color:SeatPalTheme.colors.text,backgroundColor:SeatPalTheme.colors.surface,fontSize:16},
 search:{minHeight:50,minWidth:76,borderRadius:12,backgroundColor:SeatPalTheme.colors.primary,justifyContent:'center',alignItems:'center',paddingHorizontal:12},searchText:{color:SeatPalTheme.colors.onPrimary,fontWeight:'700',fontSize:15},
 gps:{minHeight:48,justifyContent:'center',alignItems:'center',padding:10,borderRadius:12,backgroundColor:SeatPalTheme.colors.selected},gpsText:{color:SeatPalTheme.colors.text,fontWeight:'600',fontSize:15},
 status:{flexDirection:'row',alignItems:'center',gap:8},error:{color:SeatPalTheme.colors.danger,fontSize:14,lineHeight:22},
 results:{gap:8},resultsTitle:{fontSize:14,fontWeight:'600',color:SeatPalTheme.colors.secondary},result:{minHeight:62,padding:13,gap:5,borderRadius:13,borderWidth:1,borderColor:SeatPalTheme.colors.border,backgroundColor:SeatPalTheme.colors.surface},resultSelected:{borderColor:SeatPalTheme.colors.primary,backgroundColor:SeatPalTheme.colors.selected},resultText:{fontSize:16,fontWeight:'600',color:SeatPalTheme.colors.text},address:{fontSize:13,lineHeight:20,color:SeatPalTheme.colors.secondary},selectionTag:{fontSize:12,fontWeight:'600',color:SeatPalTheme.colors.secondary},
 mapFrame:{height:260,overflow:'hidden',borderRadius:16,backgroundColor:SeatPalTheme.colors.subtle},map:{flex:1},provider:{gap:5},providerText:{fontSize:12,color:SeatPalTheme.colors.secondary},policy:{fontSize:12,color:SeatPalTheme.colors.secondary,textDecorationLine:'underline',paddingVertical:5},
 footer:{paddingHorizontal:16,paddingVertical:12,borderTopWidth:1,borderColor:SeatPalTheme.colors.border,gap:8,backgroundColor:SeatPalTheme.colors.page},selected:{color:SeatPalTheme.colors.text,fontWeight:'600',fontSize:15},buttons:{flexDirection:'row',gap:10},cancel:{flex:1,minHeight:50,padding:12,borderRadius:13,backgroundColor:SeatPalTheme.colors.selected,alignItems:'center',justifyContent:'center'},confirm:{flex:1,minHeight:50,padding:12,borderRadius:13,backgroundColor:SeatPalTheme.colors.primary,alignItems:'center',justifyContent:'center'},cancelText:{color:SeatPalTheme.colors.text,fontWeight:'700',fontSize:15},confirmText:{color:SeatPalTheme.colors.onPrimary,fontWeight:'700',fontSize:15},disabled:{opacity:.45},
});
