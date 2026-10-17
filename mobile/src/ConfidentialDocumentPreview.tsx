import {SeatPalLoader} from './SeatPalLoader';
import React,{useEffect,useRef,useState} from 'react';
import {Dimensions,Image,Pressable,ScrollView,StyleSheet,View} from 'react-native';
import {Api} from './api';
import {AppText} from './NativeTypography';
import {SeatPalTheme} from './SeatPalTheme';

type Props={api:Api;user:any;documentId:string;endpoint:'identity'|'driver';lang:string;onClose:()=>void;onPageOpened:(page:number,pageCount:number)=>void;onError?:(error:unknown)=>void};
const labels={
 en:{title:'Confidential review-only preview',loading:'Preparing page…',previous:'Previous page',next:'Next page',close:'Close preview',page:'Page',of:'of',retry:'Retry page',unavailable:'This page could not be displayed. Retry when your connection is available.',reviewAccess:'Reviewer access is no longer available. Close this screen and reload your account.',watermark:'Watermarked review copy. Do not save or share.',screenshots:'The app cannot guarantee prevention of screenshots or screen recording.',zoomIn:'Zoom in',zoomOut:'Zoom out',reviewAll:'Review every page before making a decision.'},
 te:{title:'ప్రైవేట్ రివ్యూ ప్రివ్యూ',loading:'పేజీ సిద్ధం అవుతోంది…',previous:'ముందు పేజీ',next:'తర్వాతి పేజీ',close:'ప్రివ్యూ మూసేయండి',page:'పేజీ',of:'లో',retry:'మళ్లీ ప్రయత్నించండి',unavailable:'ఈ పేజీ చూపలేకపోయాం. కనెక్షన్ ఉన్నప్పుడు మళ్లీ ప్రయత్నించండి.',reviewAccess:'రివ్యూవర్ అనుమతి లేదు. ఈ స్క్రీన్ మూసి అకౌంట్‌ను మళ్లీ లోడ్ చేయండి.',watermark:'రివ్యూ కాపీపై వాటర్‌మార్క్ ఉంది. సేవ్ లేదా షేర్ చేయవద్దు.',screenshots:'స్క్రీన్‌షాట్ లేదా స్క్రీన్ రికార్డింగ్‌ను యాప్ నిరోధిస్తుందని హామీ ఇవ్వలేం.',zoomIn:'పెద్దగా చూడండి',zoomOut:'చిన్నగా చూడండి',reviewAll:'నిర్ణయం తీసుకునే ముందు ప్రతి పేజీని పరిశీలించండి.'},
 hi:{title:'गोपनीय समीक्षा प्रीव्यू',loading:'पेज तैयार हो रहा है…',previous:'पिछला पेज',next:'अगला पेज',close:'प्रीव्यू बंद करें',page:'पेज',of:'में से',retry:'पेज फिर लोड करें',unavailable:'यह पेज नहीं दिख सका। कनेक्शन मिलने पर फिर कोशिश करें।',reviewAccess:'समीक्षक की अनुमति नहीं है। यह स्क्रीन बंद करके खाते को फिर लोड करें।',watermark:'वॉटरमार्क वाली समीक्षा प्रति। सेव या शेयर न करें।',screenshots:'ऐप स्क्रीनशॉट या स्क्रीन रिकॉर्डिंग रोकने की गारंटी नहीं देता।',zoomIn:'ज़ूम करें',zoomOut:'ज़ूम कम करें',reviewAll:'निर्णय लेने से पहले हर पेज देखें।'}
} as const;

/** Staff review only: authenticated watermarked raster pages remain as data in component memory. */
export function ConfidentialDocumentPreview({api,user,documentId,endpoint,lang,onClose,onPageOpened,onError}:Props){
 const text=(labels as any)[lang]||labels.en;
 const capabilities=user?.access?.staff_capabilities||user?.staff_capabilities||[];
 const reviewerAuthorized=user?.access?.is_staff===true&&Array.isArray(capabilities)&&capabilities.includes('verify.review');
 const [page,setPage]=useState(1),[pageCount,setPageCount]=useState(1),[image,setImage]=useState(''),[watermark,setWatermark]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[zoom,setZoom]=useState(1),[imageRatio,setImageRatio]=useState(1.42);
 const generation=useRef(0),flight=useRef(false),active=useRef(true),token=useRef(api.token),actor=useRef(String(user?.id||'')),authorized=useRef(reviewerAuthorized);authorized.current=reviewerAuthorized;
 const current=()=>active.current&&authorized.current&&api.token===token.current&&String(user?.id||'')===actor.current;
 const loadPage=async(next:number)=>{
  if(flight.current||!current())return;
  const request=++generation.current;flight.current=true;setBusy(true);setError('');setImage('');setWatermark('');setPage(next);
  try{
   const result=await api.documentPreview(endpoint,documentId,next);
   if(!current()||request!==generation.current)return;
   if(typeof result.image_data_url!=='string'||!/^data:image\/jpeg;base64,[A-Za-z0-9+/]+=*$/.test(result.image_data_url)||!Number.isInteger(result.page_count)||result.page_count<1||result.page_count>12||next>result.page_count||result.page!==next)throw new Error(text.unavailable);
   setImage(result.image_data_url);setPageCount(result.page_count);setWatermark(String(result.watermark||''));
  }catch(cause){if(current()&&request===generation.current){setError(text.unavailable);onError?.(cause);}}
  finally{if(current()&&request===generation.current){flight.current=false;setBusy(false);}}
 };
 useEffect(()=>{active.current=true;token.current=api.token;actor.current=String(user?.id||'');authorized.current=reviewerAuthorized;setImage('');setWatermark('');setPage(1);setPageCount(1);if(reviewerAuthorized)void loadPage(1);else{generation.current++;flight.current=false;setBusy(false);setError(text.reviewAccess);}return()=>{active.current=false;generation.current++;flight.current=false;};},[api,api.token,user?.id,documentId,endpoint,reviewerAuthorized]);
 const button=(label:string,action:()=>void,disabled=false,allowWhileBusy=false)=><Pressable accessibilityRole="button" accessibilityState={{disabled:disabled||busy&&!allowWhileBusy}} disabled={disabled||busy&&!allowWhileBusy} onPress={action} style={[styles.button,(disabled||busy&&!allowWhileBusy)&&styles.disabled]}><AppText style={styles.buttonText}>{label}</AppText></Pressable>;
 const renderGeneration=generation.current;
 const imageWidth=Math.max(280,Dimensions.get('window').width-60)*zoom;
 return <View style={styles.panel}>
  <AppText style={styles.title}>{text.title}</AppText>
  <AppText style={styles.note}>{text.watermark}</AppText>
  <AppText style={styles.note}>{text.screenshots}</AppText><AppText style={styles.note}>{text.reviewAll}</AppText>
  <View style={styles.frame}>{reviewerAuthorized&&image?<ScrollView horizontal contentContainerStyle={styles.scrollContent}><ScrollView nestedScrollEnabled contentContainerStyle={styles.scrollContent}><Image key={`${documentId}-${page}-${renderGeneration}`} source={{uri:image}} style={{width:imageWidth,height:imageWidth*imageRatio}} resizeMode="stretch" accessible accessibilityLabel={watermark||text.title} onLoad={event=>{if(!current()||renderGeneration!==generation.current)return;const {width,height}=event.nativeEvent.source;if(width&&height)setImageRatio(height/width);onPageOpened(page,pageCount);}} onError={()=>{if(!current()||renderGeneration!==generation.current)return;setImage('');setWatermark('');setError(text.unavailable);}}/></ScrollView></ScrollView>:busy&&reviewerAuthorized?<SeatPalLoader label={text.loading}/>:<AppText accessibilityRole="alert" style={styles.error}>{reviewerAuthorized?error||text.unavailable:text.reviewAccess}</AppText>}</View>
  {reviewerAuthorized&&watermark?<AppText style={styles.watermark}>{watermark}</AppText>:null}
  {error&&!busy?button(text.retry,()=>void loadPage(page)):null}
  <View style={styles.controls}>{button(text.previous,()=>void loadPage(page-1),page<=1||busy)}<AppText style={styles.page}>{text.page} {page} {text.of} {pageCount}</AppText>{button(text.next,()=>void loadPage(page+1),page>=pageCount||busy)}</View>
  <View style={styles.controls}>{button(text.zoomOut,()=>setZoom(value=>Math.max(1,value/1.5)),zoom<=1)}<AppText style={styles.page}>{Math.round(zoom*100)}%</AppText>{button(text.zoomIn,()=>setZoom(value=>Math.min(3,value*1.5)),zoom>=3)}</View>
  {button(text.close,()=>{generation.current++;flight.current=false;setImage('');setWatermark('');onClose();},false,true)}
 </View>;
}

const styles=StyleSheet.create({panel:{padding:14,gap:10,borderRadius:16,backgroundColor:SeatPalTheme.colors.surface,borderWidth:1,borderColor:SeatPalTheme.colors.border},title:{fontSize:17,fontWeight:'700',color:SeatPalTheme.colors.text},note:{fontSize:12,lineHeight:18,color:SeatPalTheme.colors.secondary},frame:{height:420,alignItems:'center',justifyContent:'center',backgroundColor:SeatPalTheme.colors.subtle,borderRadius:10,overflow:'hidden'},scrollContent:{alignItems:'center',justifyContent:'center'},watermark:{fontSize:11,color:SeatPalTheme.colors.secondary},controls:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:8},page:{fontSize:13,color:SeatPalTheme.colors.secondary,fontWeight:'600'},button:{flex:1,minHeight:44,padding:10,alignItems:'center',justifyContent:'center',backgroundColor:SeatPalTheme.colors.primary,borderRadius:12},buttonText:{fontSize:13,fontWeight:'700',color:SeatPalTheme.colors.onPrimary,textAlign:'center'},disabled:{opacity:.4},error:{padding:16,color:SeatPalTheme.colors.danger,textAlign:'center'}});
