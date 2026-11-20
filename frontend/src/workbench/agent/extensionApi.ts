import { apiUrl, readResponse } from "../../api";
import type { RequestOf, ResponseOf, Schema } from "../../apiTypes";
export type ExtensionCatalog = ResponseOf<"/projects/agent-extensions", "get">;
export type ExtensionManifest = Schema<"ExtensionManifestView">;
const path = (root:string, suffix="")=>apiUrl(`/projects/agent-extensions${suffix}?project_root=${encodeURIComponent(root)}`);
export async function getExtensions(root:string):Promise<ExtensionCatalog> {
  return readResponse(await fetch(path(root)));
}
export async function reviewExtensions(root:string, manifest:Record<string,unknown>):Promise<ExtensionCatalog> {
  return readResponse(await fetch(path(root,"/review"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({manifest})}));
}
export async function admitExtensions(root:string, body:RequestOf<"/projects/agent-extensions","put">):Promise<ExtensionCatalog> {
  return readResponse(await fetch(path(root),{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}));
}
export async function disableExtension(root:string,id:string,disabled:boolean,expected_sha256:string):Promise<ExtensionCatalog> {
  return readResponse(await fetch(path(root,"/disable"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id,disabled,expected_sha256})}));
}
