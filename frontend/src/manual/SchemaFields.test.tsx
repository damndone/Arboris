import { useState } from 'react';
import { fireEvent, render, screen, cleanup, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { SchemaField } from './SchemaFields';
import { initialValue, validateValue, type JsonSchema } from './schemaModel';
afterEach(cleanup);
function Form({schema,initial}:{schema:JsonSchema;initial?:unknown}) {
  const [value,setValue]=useState(initial ?? initialValue(schema));
  return <><SchemaField schema={schema} label="Parameters" value={value} onChange={setValue} required/><output data-testid="value">{JSON.stringify(value)}</output></>;
}
it('builds nested weight maps and restriction arrays without JSON syntax',()=>{
  const schema: JsonSchema = {
    type: 'object', required: ['constraints'], additionalProperties: false,
    properties: {constraints: {type: 'array', minItems: 1, items: {
      type: 'object', required: ['terms', 'value'], additionalProperties: false,
      properties: {terms: {type: 'object', minProperties: 1, additionalProperties: {type: 'number'}}, value: {type: 'number'}},
    }}},
  };
  render(<Form schema={schema}/>);
  fireEvent.click(screen.getByRole('button',{name:'Add Parameters.constraints item'}));
  fireEvent.change(screen.getByLabelText('Parameters.constraints[1].terms new field name'),{target:{value:'x'}});
  fireEvent.click(screen.getByRole('button',{name:'Add Parameters.constraints[1].terms field'}));
  fireEvent.change(screen.getByLabelText('Parameters.constraints[1].terms.x'),{target:{value:'1'}});
  fireEvent.change(screen.getByLabelText('Parameters.constraints[1].value'),{target:{value:'0'}});
  expect(JSON.parse(screen.getByTestId('value').textContent!)).toEqual({constraints:[{terms:{x:1},value:0}]});
  expect(document.querySelector('textarea')).toBeNull();
});
it('distinguishes an omitted field from explicit null, false and zero',()=>{
  render(<Form schema={{type:'object',additionalProperties:false,properties:{option:{type:['number','null']},flag:{type:'boolean'}}}}/>);
  expect(screen.getByTestId('value')).toHaveTextContent('{}');
  fireEvent.change(screen.getByLabelText('Parameters optional field'),{target:{value:'option'}});
  fireEvent.change(screen.getByLabelText('Parameters.option value type'),{target:{value:'1'}});
  expect(screen.getByTestId('value')).toHaveTextContent('{"option":null}');
  fireEvent.change(screen.getByLabelText('Parameters.option value type'),{target:{value:'0'}});
  expect(screen.getByTestId('value')).toHaveTextContent('{"option":0}');
  fireEvent.change(screen.getByLabelText('Parameters optional field'),{target:{value:'flag'}});
  expect(screen.getByTestId('value')).toHaveTextContent('{"option":0,"flag":false}');
  fireEvent.click(screen.getByRole('button',{name:'Remove Parameters.option'}));
  expect(screen.getByTestId('value')).toHaveTextContent('{"flag":false}');
});
it('reorders values without changing their type or losing nested fields',()=>{
  render(<Form schema={{type:'array'}} initial={[{x:1},'two',null]}/>);
  fireEvent.click(screen.getByRole('button',{name:'Move Parameters item 2 up'}));
  expect(screen.getByTestId('value')).toHaveTextContent('["two",{"x":1},null]');
  fireEvent.click(screen.getByRole('button',{name:'Remove Parameters item 1'}));
  expect(screen.getByTestId('value')).toHaveTextContent('[{"x":1},null]');
  expect(screen.getByLabelText('Parameters[1].x')).toHaveValue(1);
});
it('enforces declared limits and resolves references without silently widening validation',()=>{
  const schema:JsonSchema={type:'object',required:['values'],additionalProperties:false,properties:{values:{$ref:'#/$defs/list'}},$defs:{list:{type:'array',minItems:1,maxItems:2,uniqueItems:true,items:{type:'integer',minimum:0}}}};
  expect(validateValue(schema,{values:[0,1]})).toEqual([]);
  for(const invalid of [{values:[]},{values:[1,1]},{values:[0,1,2]},{values:[0.5]},{values:[-1]},{values:[0],other:1}]) expect(validateValue(schema,invalid).length).toBeGreaterThan(0);
  expect(validateValue({type:'number',nullable:true},null)).toEqual([]);
  expect(validateValue({oneOf:[{type:'number'},{type:'string'}]},false).length).toBe(1);
  expect(validateValue({oneOf:[{type:'number'},{type:'integer'}]},1).length).toBe(1);
});
it('refuses duplicate map keys and preserves unusual literal names',()=>{
  render(<Form schema={{type:'object',additionalProperties:{type:'string'}}} initial={{"a'b":'original'}}/>);
  fireEvent.change(screen.getByLabelText('Parameters new field name'),{target:{value:"a'b"}});
  expect(screen.getByRole('button',{name:'Add Parameters field'})).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Parameters new field name'),{target:{value:'__proto__'}});
  fireEvent.click(screen.getByRole('button',{name:'Add Parameters field'}));
  fireEvent.change(screen.getByLabelText('Parameters.__proto__'),{target:{value:'literal'}});
  expect(JSON.parse(screen.getByTestId('value').textContent!)).toEqual(JSON.parse('{"a\'b":"original","__proto__":"literal"}'));
});

it('reads as words, hides a field with one allowed value, and edits name lists as chips',()=>{
  const schema:JsonSchema={type:'object',required:['input_mode','column_bindings'],additionalProperties:false,properties:{
    input_mode:{type:'string',enum:['frame']},
    column_bindings:{type:'object',required:['columns'],additionalProperties:false,properties:{columns:{type:'array',minItems:2,items:{type:'string',minLength:1}}}},
  }};
  function Columns(){const [value,setValue]=useState(initialValue(schema));return <><SchemaField schema={schema} label="Step 1" value={value} onChange={setValue} required columns={['wage','age','educ']} flat/><output data-testid="value">{JSON.stringify(value)}</output></>;}
  render(<Columns/>);
  expect(screen.queryByText(/Input mode/)).toBeNull();
  expect(screen.getByText(/^Column bindings/)).toBeInTheDocument();
  expect(screen.queryByText('Step 1')).toBeNull();
  const group=screen.getByRole('group',{name:'Columns in this dataset for Columns'});
  fireEvent.click(within(group).getByRole('button',{name:'wage'}));
  fireEvent.change(screen.getByLabelText('Step 1.column_bindings.columns new item'),{target:{value:'age'}});
  fireEvent.keyDown(screen.getByLabelText('Step 1.column_bindings.columns new item'),{key:'Enter'});
  expect(JSON.parse(screen.getByTestId('value').textContent!)).toEqual({input_mode:'frame',column_bindings:{columns:['wage','age']}});
  expect(within(group).getByRole('button',{name:'age'})).toHaveAttribute('aria-pressed','true');
  fireEvent.click(screen.getByRole('button',{name:'Remove Step 1.column_bindings.columns item 1'}));
  expect(JSON.parse(screen.getByTestId('value').textContent!).column_bindings.columns).toEqual(['age']);
});

// Opt-in integration audit reads the delivered catalog rather than a copied fixture.
import { readFileSync, writeFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterAll } from 'vitest';
import { resolveSchema, seedValue } from './schemaModel';
const catalogPath = process.env.MANUAL_CATALOG_PATH;
if (catalogPath) {
  const catalog = JSON.parse(readFileSync(catalogPath, 'utf8')) as {operations: {id:string;execution:{kind:string};spec_schema:JsonSchema}[]};
  const coverage:{id:string;kind:string;fields:number}[]=[];
  for(const operation of catalog.operations) it(`renders all declared fields without JSON input: ${operation.id}`,()=>{
    const root=operation.spec_schema;
    let fields=0;
    function visit(raw:JsonSchema,path:string,ancestors:Set<JsonSchema>) {
      const schema=resolveSchema(raw,root);
      if(ancestors.has(raw))return;
      const html=renderToStaticMarkup(<SchemaField schema={schema} root={root} label={path} required value={seedValue(schema,root)} onChange={()=>{}}/>);
      expect(html).not.toContain('<textarea');
      expect(html).not.toContain('role="alert"');
      fields++;
      const next=new Set(ancestors).add(raw);
      for(const [name,child] of Object.entries(schema.properties??{})) visit(child,`${path}.${name}`,next);
      if(schema.items)visit(schema.items,`${path}[]`,next);
      if(typeof schema.additionalProperties==='object')visit(schema.additionalProperties,`${path}.*`,next);
      for(const branch of schema.anyOf??schema.oneOf??[]) visit(branch,`${path}.variant`,next);
    }
    visit(root,operation.id,new Set());
    coverage.push({id:operation.id,kind:operation.execution.kind,fields});
  });
  afterAll(()=>{if(process.env.MANUAL_COVERAGE_PATH)writeFileSync(process.env.MANUAL_COVERAGE_PATH,JSON.stringify({catalog_count:catalog.operations.length,covered:coverage.length,operations:coverage},null,2));});
}
