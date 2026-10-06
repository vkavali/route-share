import React, {useCallback, useEffect, useMemo, useRef} from 'react';
import {Linking, StyleProp, StyleSheet, View, ViewStyle} from 'react-native';
import {WebView} from 'react-native-webview';
import type {WebViewMessageEvent, WebViewProps} from 'react-native-webview';
import {LEAFLET_CSS, LEAFLET_JS} from './generated/leaflet';

type Coordinate = [number, number];
type LocationPoint = {
  lat?: unknown;
  lon?: unknown;
  name?: unknown;
  id?: unknown;
  user_id?: unknown;
};
type MapLocation = {key: string; lat: number; lon: number; name: string};
type MapStop = {key: string; lat: number; lon: number; name: string; kind: 'pickup'|'dropoff'};
type MapPayload = {coordinates: Coordinate[]; locations: MapLocation[]; stops: MapStop[]};
type NavigationRequest = Parameters<NonNullable<WebViewProps['onShouldStartLoadWithRequest']>>[0];
type MessageEvent = WebViewMessageEvent;

const OSM_COPYRIGHT = 'https://www.openstreetmap.org/copyright';
const REGIONAL_CENTER: Coordinate = [80, 17.1];
const validCoordinate = (value: unknown): value is Coordinate =>
  Array.isArray(value) && value.length >= 2 &&
  typeof value[0] === 'number' && Number.isFinite(value[0]) && Math.abs(value[0]) <= 180 &&
  typeof value[1] === 'number' && Number.isFinite(value[1]) && Math.abs(value[1]) <= 90;

function buildPayload(coordinates: Coordinate[] = [], locations: LocationPoint[] = [], stops: {lat:number;lon:number;label?:string;kind:'pickup'|'dropoff'}[] = []): MapPayload {
  const route = Array.isArray(coordinates) && coordinates.length >= 2 && coordinates.every(validCoordinate)
    ? coordinates.map(([lon, lat]) => [lon, lat] as Coordinate)
    : [];
  const live = Array.isArray(locations) ? locations : [];
  const participants: MapLocation[] = [];
  live.forEach((point, index) => {
    if (!point || typeof point.lat !== 'number' || !Number.isFinite(point.lat) || Math.abs(point.lat) > 90 ||
      typeof point.lon !== 'number' || !Number.isFinite(point.lon) || Math.abs(point.lon) > 180) return;
    const id = typeof point.user_id === 'string' && point.user_id ? point.user_id
      : typeof point.id === 'string' && point.id ? point.id : `location-${index}`;
    participants.push({
      key: id.slice(0, 100),
      lat: point.lat,
      lon: point.lon,
      name: typeof point.name === 'string' ? point.name.slice(0, 80) : ''
    });
  });
  const pins: MapStop[] = Array.isArray(stops) ? stops.slice(0,2).flatMap((point,index) => {
    if (!point || typeof point.lat !== 'number' || !Number.isFinite(point.lat) || Math.abs(point.lat)>90 ||
      typeof point.lon !== 'number' || !Number.isFinite(point.lon) || Math.abs(point.lon)>180) return [];
    return [{key:`stop-${index}`,lat:point.lat,lon:point.lon,name:typeof point.label==='string'?point.label.slice(0,100):'',kind:point.kind}];
  }) : [];
  return {coordinates: route, locations: participants, stops:pins};
}

function safeJson(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

function buildHtml(lang = 'en'): string {
  const center = safeJson(REGIONAL_CENTER);
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; object-src 'none'; frame-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: https://tile.openstreetmap.org; font-src data:"><style>html,body,#map{width:100%;height:100%;margin:0;background:#F5F4EC;overflow:hidden}#map{font-family:system-ui,-apple-system,'Segoe UI',sans-serif}${LEAFLET_CSS}.leaflet-control-attribution{font-size:10px}.leaflet-control a{color:#153C32}</style></head><body><div id="map" role="application" aria-label="OpenStreetMap route and live locations"></div><script>${LEAFLET_JS}</script><script>
(function(){
  var OSM_COPYRIGHT=${safeJson(OSM_COPYRIGHT)};
  var LANGUAGE=${safeJson(lang)};
  var center=${center};
  var map=L.map('map',{zoomControl:true,attributionControl:true,scrollWheelZoom:true,keyboard:true,zoomAnimation:false,fadeAnimation:false,markerZoomAnimation:false});
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="'+OSM_COPYRIGHT+'">OpenStreetMap contributors</a>'}).addTo(map);
  map.setView([center[1],center[0]],7);
  var routeLine=null,originMarker=null,destinationMarker=null;
  var liveMarkers=new Map(),stopMarkers=new Map();
  var hasInitialRouteFit=false,hasInitialLocationView=false,lastStopSignature='';
  function validLatLon(lat,lon){return Number.isFinite(lat)&&Number.isFinite(lon)&&Math.abs(lat)<=90&&Math.abs(lon)<=180;}
  function markerPopup(marker,name){
    if(!name)return;
    var content=document.createElement('span');
    content.textContent=name;
    if(marker.getPopup())marker.setPopupContent(content);else marker.bindPopup(content);
  }
  function update(data){
    if(!data||!Array.isArray(data.coordinates)||!Array.isArray(data.locations)||!Array.isArray(data.stops))return;
    var points=data.coordinates.filter(function(p){return Array.isArray(p)&&p.length>=2&&validLatLon(p[1],p[0]);});
    if(points.length<2)points=[];
    if(points.length){
      var latlngs=points.map(function(p){return [p[1],p[0]];});
      if(!routeLine)routeLine=L.polyline(latlngs,{color:'#153C32',weight:5,opacity:.94,lineCap:'round',lineJoin:'round'}).addTo(map);
      else routeLine.setLatLngs(latlngs);
      if(!originMarker)originMarker=L.circleMarker(latlngs[0],{radius:8,color:'#fff',weight:3,fillColor:'#D8ED79',fillOpacity:1}).addTo(map);
      else originMarker.setLatLng(latlngs[0]);
      if(!destinationMarker)destinationMarker=L.circleMarker(latlngs[latlngs.length-1],{radius:8,color:'#fff',weight:3,fillColor:'#153C32',fillOpacity:1}).addTo(map);
      else destinationMarker.setLatLng(latlngs[latlngs.length-1]);
      if(!hasInitialRouteFit){map.fitBounds(routeLine.getBounds(),{padding:[28,28],maxZoom:15});hasInitialRouteFit=true;}
    }else{
      if(routeLine){map.removeLayer(routeLine);routeLine=null;}
      if(originMarker){map.removeLayer(originMarker);originMarker=null;}
      if(destinationMarker){map.removeLayer(destinationMarker);destinationMarker=null;}
    }
    var present=new Set();
    data.locations.forEach(function(point,index){
      if(!point||!validLatLon(point.lat,point.lon))return;
      var key=typeof point.key==='string'&&point.key?point.key:'location-'+index;
      present.add(key);
      var marker=liveMarkers.get(key);
      if(!marker){marker=L.circleMarker([point.lat,point.lon],{radius:9,color:'#fff',weight:3,fillColor:'#D8ED79',fillOpacity:.96}).addTo(map);liveMarkers.set(key,marker);}
      else marker.setLatLng([point.lat,point.lon]);
      markerPopup(marker,typeof point.name==='string'?point.name.slice(0,80):'');
    });
    liveMarkers.forEach(function(marker,key){if(!present.has(key)){map.removeLayer(marker);liveMarkers.delete(key);}});
    var stopPoints=[];
    data.stops.forEach(function(point,index){
      if(!point||!validLatLon(point.lat,point.lon))return;
      var key=typeof point.key==='string'?point.key:'stop-'+index;
      stopPoints.push([point.lat,point.lon]);
      var marker=stopMarkers.get(key);
      var color=point.kind==='pickup'?'#D8ED79':'#153C32';
      if(!marker){marker=L.circleMarker([point.lat,point.lon],{radius:8,color:'#fff',weight:3,fillColor:color,fillOpacity:1}).addTo(map);stopMarkers.set(key,marker);}
      else marker.setLatLng([point.lat,point.lon]).setStyle({fillColor:color});
      markerPopup(marker,typeof point.name==='string'?point.name.slice(0,100):'');
    });
    stopMarkers.forEach(function(marker,key){if(!data.stops.some(function(point,index){return (typeof point.key==='string'?point.key:'stop-'+index)===key;})){map.removeLayer(marker);stopMarkers.delete(key);}});
    if(!points.length&&stopPoints.length){
      var signature=stopPoints.map(function(point){return point[0].toFixed(5)+','+point[1].toFixed(5);}).join('|');
      if(signature!==lastStopSignature){
        if(stopPoints.length===1)map.setView(stopPoints[0],13);
        else map.fitBounds(stopPoints,{padding:[24,24],maxZoom:14});
        lastStopSignature=signature;
      }
    }
    if(!points.length&&!hasInitialRouteFit&&data.locations.length&&!hasInitialLocationView){
      var first=data.locations.find(function(point){return point&&validLatLon(point.lat,point.lon);});
      if(first){map.setView([first.lat,first.lon],13);hasInitialLocationView=true;}
    }
  }
  window.__updateRouteMap=update;
  window.__routeMapReady=true;
  document.addEventListener('click',function(event){
    var target=event.target;
    var anchor=target instanceof Element?target.closest('a'):null;
    if(!anchor||!event.isTrusted)return;
    var href=anchor.href;
    if(href===OSM_COPYRIGHT&&window.ReactNativeWebView){event.preventDefault();window.ReactNativeWebView.postMessage('open:osm-copyright');}
  });
})();
</script></body></html>`;
}

export function RouteMap({coordinates = [], locations = [], stops = [], height = 300, style, lang='en'}: {coordinates: Coordinate[]; locations: LocationPoint[]; stops?:{lat:number;lon:number;label?:string;kind:'pickup'|'dropoff'}[]; height?:number; style?:StyleProp<ViewStyle>; lang?:string}) {
  const webView = useRef<WebView>(null);
  const ready = useRef(false);
  const payload = safeJson(buildPayload(coordinates, locations, stops));
  const latestPayload = useRef(payload);
  latestPayload.current = payload;
  const html = useMemo(()=>buildHtml(lang), [lang]);
  const injectPayload = useCallback((serialized: string) => {
    webView.current?.injectJavaScript(`if(window.__routeMapReady&&window.__updateRouteMap)window.__updateRouteMap(${serialized});true;`);
  }, []);

  useEffect(() => {
    if (ready.current) injectPayload(payload);
  }, [injectPayload, payload]);

  const onLoadEnd = useCallback(() => {
    ready.current = true;
    injectPayload(latestPayload.current);
  }, [injectPayload]);

  const onMessage = useCallback((event: MessageEvent) => {
    if (event.nativeEvent.data === 'open:osm-copyright') {
      void Linking.openURL(OSM_COPYRIGHT).catch(() => undefined);
    }
  }, []);

  const onShouldStartLoadWithRequest = useCallback((request: NavigationRequest) => {
    if (request.isTopFrame === false) return false;
    if (request.url === 'about:blank') return true;
    try {
      const target = new URL(request.url);
      return target.protocol === 'https:' && target.hostname === 'localhost' && target.port === '' &&
        target.username === '' && target.password === '' && target.pathname === '/' && !target.search && !target.hash;
    } catch {
      return false;
    }
  }, []);

  return <View style={[styles.wrap, {height}, style]}>
    <WebView
      ref={webView}
      source={{html, baseUrl: 'https://localhost'}}
      originWhitelist={['https://localhost', 'about:blank']}
      onLoadEnd={onLoadEnd}
      onMessage={onMessage}
      onShouldStartLoadWithRequest={onShouldStartLoadWithRequest}
      javaScriptEnabled
      allowFileAccess={false}
      allowUniversalAccessFromFileURLs={false}
      mixedContentMode="never"
      applicationNameForUserAgent="RouteShareLocalBeta/0.1"
      style={styles.map}
    />
  </View>;
}

const styles = StyleSheet.create({wrap: {height: 300, borderRadius: 16, overflow: 'hidden', backgroundColor: '#E9EEE6'}, map: {flex: 1}});
