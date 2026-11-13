// Preview production-path artifacts against the reviewed local API source.
// Provider responses come from that API; this helper does not invent values.
export async function installLocalApiRouting(socket,send,siteBase) {
  const target=process.env.STOCK_LOCAL_API;
  if(!target)return {async disable(){}};
  const url=new URL(target);
  if(!["127.0.0.1","localhost"].includes(url.hostname)||url.protocol!=="http:")throw new Error("Preview API must be local");
  const listener=event=>{
    const value=JSON.parse(event.data);
    if(value.method!=="Fetch.requestPaused")return;
    const {requestId,request}=value.params;
    void (async()=>{
      const response=await fetch(target+"/refresh",{method:request.method,headers:{"Content-Type":"application/json",Origin:new URL(siteBase).origin},...(["GET","HEAD","OPTIONS"].includes(request.method)?{}:{body:request.postData}),signal:AbortSignal.timeout(90000)});
      await send("Fetch.fulfillRequest",{requestId,responseCode:response.status,responseHeaders:[...response.headers].filter(([name])=>!["content-length","transfer-encoding","connection","keep-alive","content-encoding"].includes(name.toLowerCase())).map(([name,value])=>({name,value})),body:Buffer.from(await response.arrayBuffer()).toString("base64")});
    })().catch(error=>{
      void send("Fetch.failRequest",{requestId,errorReason:"Failed"}).catch(()=>{});
      if(!/interception|closed|timeout/i.test(error.message))console.error("Local preview API:",error.message);
    });
  };
  socket.addEventListener("message",listener);
  await send("Fetch.enable",{patterns:[{urlPattern:"*/refresh",requestStage:"Request"}]});
  return {async disable(){socket.removeEventListener("message",listener);await send("Fetch.disable");}};
}
