import {test,expect} from '@playwright/test';
test('real preloaded epochs use existing comparison, remain gated, and reuse results offline',async({page})=>{
  const archive=[];
  await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(!['localhost','127.0.0.1'].includes(url.hostname)){archive.push(url.href);return route.abort();}
    return route.continue();
  });
  await page.goto('/?mode=demo');
  await expect(page.getByRole('region',{name:'Scientific Detection Lab'})).toHaveCount(0);
  await page.locator('#demo-target').selectOption('m31');
  const slider=page.getByRole('region',{name:'Astronomical time explorer'});
  await slider.getByRole('slider').fill('4');
  const epochs=slider.getByRole('region',{name:'Epoch change analysis'});
  await expect(epochs).toContainText('2026W01_1A_0471_1');
  let calls=0;page.on('request',r=>{if(new URL(r.url()).pathname==='/api/compare')calls++;});
  await epochs.getByRole('button',{name:'Compare with previous observation'}).click();
  const comparison=epochs.getByRole('region',{name:'Image comparison'});
  await comparison.getByRole('button',{name:'Find Changes'}).click();
  await expect(comparison.getByTestId('compare-result')).toBeVisible({timeout:60000});
  await expect(comparison).toContainText('No astronomical change is established');
  await comparison.getByText('How did we reach this conclusion?',{exact:true}).click();
  await expect(comparison).toContainText('Calibrated per-pixel wavelength');
  await slider.getByRole('slider').fill('3');
  await slider.getByRole('slider').fill('4');
  await expect(epochs).toContainText('Assessed pair:');
  expect(calls).toBe(1);
  expect(archive).toEqual([]);
  await epochs.screenshot({path:'test-results/real-epoch-analysis.png'});
});
