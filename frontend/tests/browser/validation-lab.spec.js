import {test,expect} from '@playwright/test';
test.skip(process.env.VITE_ENABLE_DETECTION_LAB !== 'true', 'Developer lab requires explicit feature flag');
test('offline real-background controlled experiments and candidate overlays',async({page})=>{
  await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(!['127.0.0.1','localhost'].includes(url.hostname))return route.abort();
    return route.continue();
  });
  await page.goto('/?mode=demo');
  const lab=page.getByRole('region',{name:'Scientific Detection Lab'});
  for(const kind of ['brightness','transient','no_change']){
    await lab.getByRole('combobox').selectOption(kind);
    await lab.getByRole('button',{name:'Run validation experiment'}).click();
    await expect(lab.getByTestId('validation-result')).toContainText('Criteria met');
    await expect(lab.getByRole('img',{name:'difference validation image'})).toBeVisible();
    await expect(lab.locator('svg circle')).toHaveCount(kind==='no_change'?0:1);
    if(kind!=='no_change'){
      await lab.getByRole('button',{name:'C1',exact:true}).click();
      await expect(lab.getByRole('status')).toContainText('Calibrated uncertainty unavailable');
    }
  }
  await lab.screenshot({path:'test-results/scientific-validation-no-change.png'});
  await lab.getByRole('combobox').selectOption('transient');
  await lab.getByRole('button',{name:'Run validation experiment'}).click();
  await expect(lab.locator('svg circle')).toHaveCount(1);
  await lab.screenshot({path:'test-results/scientific-validation-transient.png'});
});

test('lab reports API failure without fabricated results',async({page})=>{
  await page.route('**/api/validation?**',route=>route.fulfill({status:422,json:{detail:'Background checksum mismatch'}}));
  await page.goto('/?mode=demo');
  const lab=page.getByRole('region',{name:'Scientific Detection Lab'});
  await lab.getByRole('button',{name:'Run validation experiment'}).click();
  await expect(lab.getByRole('alert')).toHaveText('Background checksum mismatch');
  await expect(lab.getByTestId('validation-result')).toHaveCount(0);
});
