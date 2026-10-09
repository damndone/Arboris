import { useId, useState } from 'react';
import { initialValue, resolveSchema, seedValue, validateValue, valueType, variants, type JsonSchema } from './schemaModel';
export { initialValue, type JsonSchema } from './schemaModel';

type Props = {
  schema: JsonSchema; value: unknown; onChange: (value: unknown) => void; label: string;
  required?: boolean; columns?: string[]; root?: JsonSchema; depth?: number;
};
const anyTypes: JsonSchema[] = [
  {type: 'string', title: 'Text'}, {type: 'number', title: 'Number'},
  {type: 'boolean', title: 'Yes / No'}, {type: 'null', title: 'Missing (null)'},
  {type: 'array', title: 'List'}, {type: 'object', title: 'Fields'},
];
const caption = (label: string, schema: JsonSchema) => schema.title ?? label.split(".").pop() ?? label;
function VariantField({branches, ...props}: Props & {branches: JsonSchema[]}) {
  const root = props.root ?? props.schema;
  const [selected, setSelected] = useState<number | null>(null);
  const resolved = branches.map(b => resolveSchema(b, root));
  const exact = props.value === undefined ? -1 : resolved.findIndex(b => validateValue(b, props.value, root).length === 0);
  const shape = resolved.findIndex(b => b.type === valueType(props.value) || b.type === 'integer' && typeof props.value === 'number');
  const index = exact >= 0 ? exact : selected ?? (shape >= 0 ? shape : -1);
  return <fieldset><legend>{caption(props.label,props.schema)}{props.required ? ' *' : ''}</legend>
    <label className="manual-field">Value type<select aria-label={`${props.label} value type`} value={index} onChange={e => {
      const next = Number(e.target.value);setSelected(next);props.onChange(seedValue(resolved[next], root));
    }}><option value={-1} disabled>Choose a value type…</option>{resolved.map((b,i) => <option key={i} value={i}>{b.title ?? (b.const !== undefined ? String(b.const) : b.enum ? b.enum.map(String).join(' / ') : typeof b.type === 'string' ? b.type : `Variant ${i + 1}`)}</option>)}</select></label>
    {index >= 0 && <FieldControl key={index} {...props} schema={resolved[index]} required/>}
  </fieldset>;
}
function ObjectField(props: Props) {
  const {schema, value, onChange, label} = props;
  const record = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string,unknown> : {};
  const [keyDraft, setKeyDraft] = useState('');
  const properties = schema.properties ?? {};
  const known = (key: string) => Object.prototype.hasOwnProperty.call(properties, key);
  const present = (key: string) => Object.prototype.hasOwnProperty.call(record, key);
  const update = (key: string, next: unknown) => onChange({...record, [key]: next});
  const remove = (key: string) => onChange(Object.fromEntries(Object.entries(record).filter(([name]) => name !== key)));
  const optional = Object.keys(properties).filter(key => !schema.required?.includes(key) && !present(key));
  const keys = [...new Set([...(schema.required ?? []), ...Object.keys(record)])];
  const extraSchema = typeof schema.additionalProperties === 'object' ? schema.additionalProperties : {};
  const extraAllowed = schema.additionalProperties !== false;
  return <fieldset><legend>{caption(label,schema)}{props.required ? ' *' : ''}</legend>
    {keys.map(key => <div key={key} className="manual-object-row">
      <SchemaField {...props} depth={(props.depth ?? 0) + 1} schema={known(key) ? properties[key] : extraSchema} value={record[key]} label={`${label}.${key}`} required onChange={next => update(key, next)}/>
      {!schema.required?.includes(key) && <button type="button" onClick={() => remove(key)} aria-label={`Remove ${label}.${key}`}>Remove field</button>}
    </div>)}
    {optional.length > 0 && <label className="manual-field">Add optional field<select aria-label={`${label} optional field`} value="" onChange={e => {
      const key=e.target.value;if(key) update(key, seedValue(properties[key], props.root ?? schema));
    }}><option value="">Choose a field…</option>{optional.map(key => <option key={key} value={key}>{properties[key].title ?? key}</option>)}</select></label>}
    {extraAllowed && <div className="manual-map-add"><label className="manual-field">Field name<input aria-label={`${label} new field name`} value={keyDraft} onChange={e => setKeyDraft(e.target.value)}/></label>
      <button type="button" disabled={!keyDraft.trim() || present(keyDraft) || known(keyDraft)} onClick={() => {update(keyDraft, seedValue(extraSchema,props.root ?? schema));setKeyDraft('');}} aria-label={`Add ${label} field`}>Add field</button>
      {(present(keyDraft)||known(keyDraft)) && <small role="alert">This field already exists or is declared above.</small>}
    </div>}
    {!keys.length && !optional.length && !extraAllowed && <small>No options are required.</small>}
  </fieldset>;
}
function ArrayField(props: Props) {
  const {schema, value, onChange, label} = props;
  const items = Array.isArray(value) ? value : [];
  const move = (index: number, delta: number) => {const next=[...items];[next[index],next[index+delta]]=[next[index+delta],next[index]];onChange(next);};
  return <fieldset><legend>{caption(label,schema)}{props.required ? ' *' : ''}</legend>
    {schema.minItems !== undefined && <small>At least {schema.minItems} items</small>}
    {items.map((item,index) => <div key={index} className="manual-array-row">
      <SchemaField {...props} depth={(props.depth ?? 0)+1} schema={schema.items ?? {}} value={item} label={`${label}[${index+1}]`} required onChange={next => onChange(items.map((v,i) => i === index ? next : v))}/>
      <div className="manual-actions"><button type="button" disabled={index===0} onClick={()=>move(index,-1)} aria-label={`Move ${label} item ${index+1} up`}>Move up</button>
      <button type="button" disabled={index===items.length-1} onClick={()=>move(index,1)} aria-label={`Move ${label} item ${index+1} down`}>Move down</button>
      <button type="button" onClick={()=>onChange(items.filter((_,i)=>i!==index))} aria-label={`Remove ${label} item ${index+1}`}>Remove item</button></div>
    </div>)}
    <button type="button" disabled={schema.maxItems!==undefined&&items.length>=schema.maxItems} onClick={()=>onChange([...items,seedValue(schema.items??{},props.root??schema)])} aria-label={`Add ${label} item`}>Add item</button>
  </fieldset>;
}
function FieldControl(props: Props) {
  const {schema:s,value,onChange,label,required,columns=[]} = props;
  const id = useId();
  const branches=variants(s);
  if(branches) return <VariantField {...props} branches={branches}/>;
  if(s.const!==undefined) return <p>{caption(label,s)}: <strong>{String(s.const)}</strong></p>;
  if(s.enum) return <label className="manual-field">{caption(label,s)}{required?' *':''}<select aria-label={label} required={required} value={value===undefined?'':JSON.stringify(value)} onChange={e=>onChange(e.target.value===''?undefined:JSON.parse(e.target.value))}><option value="">Choose…</option>{s.enum.map(v=><option key={JSON.stringify(v)} value={JSON.stringify(v)}>{String(v)}</option>)}</select></label>;
  if(s.type==='object'||s.properties) return <ObjectField {...props}/>;
  if(s.type==='array') return <ArrayField {...props}/>;
  if(s.type==='null') return <p>{caption(label,s)}: Missing (null)</p>;
  if(s.type==='boolean') return <label className="manual-field">{caption(label,s)}<select aria-label={label} required={required} value={value===undefined?'':String(value)} onChange={e=>onChange(e.target.value===''?undefined:e.target.value==='true')}><option value="">Choose…</option><option value="true">Yes</option><option value="false">No</option></select></label>;
  if(s.type==='number'||s.type==='integer') return <label className="manual-field">{caption(label,s)}{required?' *':''}<input aria-label={label} type="number" step={s.type==='integer'?1:'any'} min={s.minimum} max={s.maximum} required={required} value={value===undefined?'':String(value)} onChange={e=>onChange(e.target.value===''?undefined:Number(e.target.value))}/></label>;
  if(s.type==='string') return <label className="manual-field">{caption(label,s)}{required?' *':''}<input aria-label={label} required={required} minLength={s.minLength} maxLength={s.maxLength} value={String(value??'')} list={id} onChange={e=>onChange(e.target.value)}/>{columns.length>0&&<datalist id={id}>{columns.map(c=><option key={c} value={c}/>)}</datalist>}</label>;
  return <VariantField {...props} branches={anyTypes}/>;
}
export function SchemaField({root,depth=0,...props}:Props) {
  const base=root??props.schema;
  let schema:JsonSchema;
  try {schema=resolveSchema(props.schema,base);} catch(error) {return <p role="alert">{String(error)}</p>;}
  if(depth>30) return <p role="alert">{props.label}: nesting exceeds the supported form depth.</p>;
  return <div className="manual-field"><FieldControl {...props} schema={schema} root={base} depth={depth}/>{schema.description&&<small>{schema.description}</small>}</div>;
}
