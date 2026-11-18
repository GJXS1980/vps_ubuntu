import { test, expect } from "@playwright/test";
test("注册后显示审核等待，未审批不可登录", async ({ page }) => {
  await page.goto("/#/account/register");
  await page.getByLabel("用户名").fill("browser-user");
  await page.getByLabel("邮箱").fill("browser@example.org");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Browser-password-unique!");
  await page.getByRole("button", { name: "注册账号" }).click();
  await expect(
    page.getByRole("heading", { name: "等待管理员审核" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "登录" }).click();
  await page.getByLabel("用户名").fill("browser-user");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Browser-password-unique!");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByText("账号待审核", { exact: true })).toBeVisible();
});

import { readFileSync } from "node:fs";
import { createHmac } from "node:crypto";
test("管理员审批、用户申请设备及两种配置领取", async ({ browser, page }) => {
  await page.goto("/#/account/register");
  await page.getByLabel("用户名").fill("portal-device-user");
  await page.getByLabel("邮箱").fill("device@example.org");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Browser-password-unique!");
  await page.getByRole("button", { name: "注册账号" }).click();
  await expect(
    page.getByRole("heading", { name: "等待管理员审核" }),
  ).toBeVisible();
  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  const a = await admin.newPage();
  await a.goto(
    "https://127.0.0.1:" +
      (process.env.PORTAL_TEST_PORT || "17444") +
      "/#/account/login",
  );
  const cred = JSON.parse(
    readFileSync(process.env.PORTAL_TEST_CREDENTIALS!, "utf8"),
  );
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const mac = createHmac("sha1", Buffer.from(cred.seed, "base64"))
    .update(counter)
    .digest();
  const otp = String(
    (mac.readUInt32BE(mac[19] & 15) & 0x7fffffff) % 1000000,
  ).padStart(6, "0");
  await a.getByLabel("用户名").fill("test-admin");
  await a.getByLabel("密码", { exact: true }).fill(cred.password);
  await a.getByLabel("管理员动态验证码").fill(otp);
  await a.getByRole("button", { name: "登录" }).click();
  await a.getByRole("link", { name: "用户审核" }).click();
  await a.getByText("portal-device-user", { exact: true }).click();
  await a.getByRole("button", { name: "批准 / 恢复" }).click();
  await a.locator(".el-message-box__btns button").last().click();
  await expect(a.getByText("操作已提交", { exact: true })).toBeVisible();
  await admin.close();
  await page.getByRole("link", { name: "登录" }).click();
  await page.getByLabel("用户名").fill("portal-device-user");
  await page
    .getByLabel("密码", { exact: true })
    .fill("Browser-password-unique!");
  await page.getByRole("button", { name: "登录" }).click();
  await page.getByLabel("设备名称").fill("测试手机");
  await page.getByRole("button", { name: "提交申请" }).click();
  await page.getByRole("link", { name: "测试手机" }).click();
  await expect(async () => {
    await page.getByRole("button", { name: "刷新状态" }).click();
    await expect(
      page.getByRole("button", { name: "下载配置" }).first(),
    ).toBeEnabled({ timeout: 800 });
  }).toPass();
  for (const [i, mode] of ["global", "proxy"].entries()) {
    const wait = page.waitForEvent("download");
    await page.getByRole("button", { name: "下载配置" }).nth(i).click();
    const download = await wait;
    expect(download.suggestedFilename()).toBe("wg-" + mode + ".conf");
    await page.getByRole("button", { name: "显示二维码" }).nth(i).click();
    await expect(
      page.getByAltText("本设备 WireGuard 配置二维码"),
    ).toBeVisible();
    await page.getByRole("button", { name: "关闭二维码" }).click();
  }
});

test("手机宽度可完成注册表单输入", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/account/register");
  await expect(page.getByRole("button", { name: "注册账号" })).toBeVisible();
  await page.getByLabel("邮箱").fill("mobile@example.org");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
