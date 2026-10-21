// Presentation helpers only: publication text is never rewritten on copy.
export function completePost(post, hashtags='') { return `${post}\n\n${hashtags}`.trim(); }
export function xWeight(value) {
  const text=value.normalize('NFC'); let urls=0;
  const remainder=text.replace(/https?:\/\/(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::[0-9]+)?(?:[/?#][^\s]*)?/g, raw=>{
    const url=raw.replace(/[.,!?;:)"\]}]+$/g,'');
    if(url.length>4096)return raw;
    urls++;return raw.slice(url.length);
  });
  return urls*23 + Array.from(remainder).reduce((n,c)=>{
    const p=c.codePointAt(0);
    return n+(p<=0x10ff || (p>=0x2000&&p<=0x200d) || (p>=0x2010&&p<=0x201f) || (p>=0x2032&&p<=0x2037)?1:2);
  },0);
}
export function generationLabel(provider) {
  if(['local','mock','demonstration'].includes(provider)) return 'Template-assisted content generation';
  if(['openai','openai_compatible'].includes(provider)) return 'External AI-generated draft';
  return 'Saved draft';
}
export function latestBatch(items) {
  const id=items.find(x=>x.generation?.metadata_json?.batch_id)?.generation.metadata_json.batch_id;
  return id ? items.filter(x=>x.generation?.metadata_json?.batch_id===id) : [];
}
