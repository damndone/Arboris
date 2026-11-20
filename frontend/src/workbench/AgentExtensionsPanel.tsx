import { useEffect, useRef, useState } from "react";
import { fetchEgress, replaceEgressPolicy, type EgressView } from "../dataView/dataViewApi";
import { getExtensions, reviewExtensions, admitExtensions, disableExtension, type ExtensionCatalog } from "./agent/extensionApi";

export function AgentExtensionsPanel({projectRoot}:{projectRoot:string}) {
  // Remount project-bound state so a pending response can never authorize another project.
  return <ProjectExtensions key={projectRoot} projectRoot={projectRoot} />;
}
function ProjectExtensions({projectRoot}:{projectRoot:string}) {
  const [catalog,setCatalog] = useState<ExtensionCatalog|null>(null);
  const [text,setText] = useState("");
  const [review,setReview] = useState<ExtensionCatalog|null>(null);
  const [busy,setBusy] = useState(false), [error,setError] = useState("");
  const live = useRef(true);
  useEffect(()=>{
    live.current=true;
    getExtensions(projectRoot).then(value=>{if(live.current){setCatalog(value);setText(JSON.stringify(value.manifest,null,2));}})
      .catch(reason=>{if(live.current)setError(String(reason));});
    return ()=>{live.current=false;};
  },[projectRoot]);
  async function run(action:()=>Promise<void>) {
    setBusy(true);setError("");
    try {await action();} catch(reason){if(live.current)setError(reason instanceof Error?reason.message:String(reason));}
    finally {if(live.current)setBusy(false);}
  }
  return <section className="ai-panel" aria-label="Agent extensions">
    <h2>Tools and hooks</h2>
    <p>Admit only a source you trust. Queries use a fixed HTTPS endpoint and return untrusted JSON; every query still needs your approval and separate sharing permission. Hooks can record or block operations, never grant permission or run code.</p>
    {error && <p role="alert">{error}</p>}
    {!catalog ? <p>Loading extensions…</p> : <>
      <ul>{[...catalog.manifest.tools,...catalog.manifest.hooks].map(entry=><li key={entry.id}>
        <strong>{entry.id}</strong> · {entry.version} · {entry.origin}
        {"endpoint" in entry ? <><p>{entry.endpoint}</p><ExtensionSharing key={catalog.sha256+entry.id} projectRoot={projectRoot} id={entry.id} /></> : <p>{entry.event}: {entry.action} · {entry.operation_ids.join(", ") || "all operations"}<br />{entry.reason}</p>}
        <button type="button" disabled={busy} onClick={()=>void run(async()=>{
          const next=await disableExtension(projectRoot,entry.id,!catalog.disabled.includes(entry.id),catalog.sha256!);
          if(live.current)setCatalog(next);
        })}>{catalog.disabled.includes(entry.id)?"Enable":"Disable"} {entry.id}</button>
      </li>)}</ul>
      <label htmlFor="extension-manifest">Extension manifest JSON</label>
      <textarea id="extension-manifest" rows={12} value={text} disabled={busy} style={{width:"100%",fontFamily:"var(--font-mono, monospace)"}}
        onChange={e=>{setText(e.target.value);setReview(null);}} />
      <button type="button" disabled={busy || new TextEncoder().encode(text).length>64000} onClick={()=>void run(async()=>{
        const next=await reviewExtensions(projectRoot,JSON.parse(text));if(live.current)setReview(next);
      })}>Review manifest</button>
      {review && <div aria-label="Reviewed extension manifest">
        <p>This exact catalog will replace the current tools and hooks and re-enable its entries. Changing the text requires another review.</p>
        <code>{review.sha256}</code>
        <button type="button" disabled={busy} onClick={()=>void run(async()=>{
          const next=await admitExtensions(projectRoot,{manifest:review.manifest,expected_sha256:review.sha256!,previous_sha256:catalog.sha256});
          if(live.current){setCatalog(next);setReview(null);}
        })}>Admit reviewed manifest</button>
      </div>}
    </>}
  </section>;
}

function ExtensionSharing({projectRoot,id}:{projectRoot:string;id:string}) {
  const [view,setView] = useState<EgressView|null>(null),[error,setError] = useState("");
  const [busy,setBusy] = useState(false);
  const live=useRef(true);
  useEffect(()=>{
    live.current=true;
    fetchEgress(projectRoot).then(next=>{if(live.current)setView(next);})
      .catch(reason=>{if(live.current)setError(String(reason));});
    return ()=>{live.current=false;};
  },[projectRoot]);
  const provider="external:"+id, allowed=view?.policy.providers[provider]?.allow.includes("extension")??false;
  return <div>
    {error && <p role="alert">{error}</p>}
    <p>{view ? (allowed?"Query arguments may be sent after each approval.":"Query sharing is blocked.") : "Loading sharing policy…"}</p>
    <button type="button" disabled={!view || busy} onClick={async()=>{
      setBusy(true);setError("");
      try {
        const current=await fetchEgress(projectRoot);
        if(!live.current)return;
        const keep=current.policy.providers[provider]?.allow.filter(value=>value!=="extension")??[];
        const next=await replaceEgressPolicy(projectRoot,{...current.policy,providers:{...current.policy.providers,
          [provider]:{allow:allowed?keep:[...keep,"extension"]}}});
        if(live.current)setView(next);
      }catch(reason){if(live.current)setError(String(reason));}
      finally{if(live.current)setBusy(false);}
    }}>{allowed?"Block":"Allow"} query sharing to {id}</button>
  </div>;
}
