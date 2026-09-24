import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../public/pages/crm_import.js', import.meta.url), 'utf8');
const {parseCrmImport: parse, mapCrmImport: map} = new Function(source.split('export function openCrmImport')[0].replace(/^import .*;\r?\n/gm, '').replace(/export /g, '') + ';return {parseCrmImport,mapCrmImport};')();
const mapping = {company_name: '0', contact_name: '1', email: '2', phone: '3'};

test('CSV upload/paste: BOM, CRLF, quoted commas, escaped quotes, embedded newline', () => {
  const rows = parse('\uFEFFCompany,Contact,Email,Phone\r\n"Acme, Inc","Pat ""PJ"" Jones",pat@example.invalid,123\r\n"Multi\nLine",,,\r\n');
  assert.equal(rows.length, 3);
  const data = map(rows, mapping);
  assert.deepEqual(data[0], {company_name: 'Acme, Inc', contact_name: 'Pat "PJ" Jones', email: 'pat@example.invalid', phone: '123'});
  assert.equal(data[1].company_name, 'Multi\nLine');
});
test('pasted tabs and no-header input', () => {
  assert.deepEqual(map(parse('Acme\tPat\tpat@example.invalid\t123'), mapping, false)[0], {company_name:'Acme',contact_name:'Pat',email:'pat@example.invalid',phone:'123'});
});
test('mapping arbitrary columns and unmapped optional fields', () => {
  assert.deepEqual(map(parse('Email,Business\nx@example.invalid,Acme'), {company_name:'1',email:'0'})[0], {company_name:'Acme',email:'x@example.invalid',contact_name:'',phone:''});
});
test('invalid quoting and empty/header-only input rejected', () => {
  for (const text of ['', '\n\n', '"unfinished', '"closed"oops', 'un"quoted']) assert.throws(() => parse(text));
  assert.throws(() => map(parse('Company,Email'), mapping), /No data/);
});
test('company mapping and unique column mapping required', () => {
  assert.throws(() => map([['Acme']], {}, false), /Company/);
  assert.throws(() => map([['Acme']], {company_name:'0', email:'0'}, false), /only one/);
});
test('bounded bytes, columns and data rows', () => {
  assert.throws(() => parse('a'.repeat(1024*1024+1)), /1 MiB/);
  assert.throws(() => parse(Array(101).fill('a').join(',')), /100 columns/);
  const rows = parse('Company\n' + Array(500).fill('Acme').join('\n'));
  assert.equal(map(rows, {company_name:'0'}).length, 500);
  assert.throws(() => map(rows, {company_name:'0'}, false), /500/);
  assert.throws(() => parse('Company\n' + Array(501).fill('Acme').join('\n')), /500/);
});
