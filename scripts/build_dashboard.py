#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成适合移动端浏览的人才房认购数据看板 (dashboard.html)
"""

import os
import json

DATA_PATH = "data/dashboard_data.json"
OUTPUT_LOCAL = "dashboard.html"
OUTPUT_ARTIFACT = "/Users/zhangyimin/.gemini/antigravity/brain/6d7bf897-08b3-44c1-bd57-b6573a192a01/dashboard.html"

with open(DATA_PATH, "r", encoding="utf-8") as f:
    raw_data = f.read()

html_template = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>畔溪悦府 · 人才房认购资格数据看板</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    /* 移动端平滑滚动与优化 */
    html, body {{
      -webkit-font-smoothing: antialiased;
      -webkit-tap-highlight-color: transparent;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    }}
    .no-scrollbar::-webkit-scrollbar {{
      display: none;
    }}
    .no-scrollbar {{
      -ms-overflow-style: none;
      scrollbar-width: none;
    }}
  </style>
</head>
<body class="bg-[var(--background)] text-[var(--foreground)] antialiased min-h-screen">

  <!-- 移动端外层容器 (适配手机屏幕宽度) -->
  <div class="max-w-md mx-auto w-full pb-16 px-4 pt-4 sm:pt-6">

    <!-- 顶部状态与标题 -->
    <header class="mb-5">
      <div class="flex items-center justify-between gap-2 mb-2">
        <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1.5 animate-pulse"></span>
          公示批次：住保售〔2026〕081号
        </span>
        <span class="text-xs text-[var(--muted-foreground)]">公示期：10.22 - 10.28</span>
      </div>
      <h1 class="text-xl font-bold tracking-tight text-[var(--foreground)] flex items-center justify-between">
        <span>罗湖·畔溪悦府 人才房</span>
        <span class="text-xs font-normal px-2 py-0.5 rounded bg-[var(--card)] border border-[var(--border)] text-[var(--muted-foreground)]">927/1031 户合格</span>
      </h1>
      <p class="text-xs text-[var(--muted-foreground)] mt-1">认购资格审核合格家庭数据画像与位次检索看板</p>

      <!-- 3个核心关键指标卡 -->
      <div class="grid grid-cols-3 gap-2.5 mt-4">
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-3 text-center shadow-xs">
          <div class="text-xs text-[var(--muted-foreground)] mb-0.5">入围家庭</div>
          <div class="text-lg font-bold text-[var(--foreground)]">931 <span class="text-xs font-normal text-[var(--muted-foreground)]">户</span></div>
          <div class="text-xs text-emerald-500 font-medium">90.3% 合格率</div>
        </div>
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-3 text-center shadow-xs">
          <div class="text-xs text-[var(--muted-foreground)] mb-0.5">在册人口</div>
          <div class="text-lg font-bold text-[var(--foreground)]">1,861 <span class="text-xs font-normal text-[var(--muted-foreground)]">人</span></div>
          <div class="text-xs text-[var(--muted-foreground)]">户均 2.0 人</div>
        </div>
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-3 text-center shadow-xs">
          <div class="text-xs text-[var(--muted-foreground)] mb-0.5">平均年龄</div>
          <div class="text-lg font-bold text-[var(--foreground)]">35.1 <span class="text-xs font-normal text-[var(--muted-foreground)]">岁</span></div>
          <div class="text-xs text-blue-500 font-medium">90后超 68%</div>
        </div>
      </div>
    </header>

    <!-- 分段导航栏 (Segmented Control Tabs) -->
    <nav class="sticky top-2 z-30 mb-5 bg-[var(--card)]/90 backdrop-blur-md p-1 rounded-xl border border-[var(--border)] shadow-sm">
      <div class="grid grid-cols-3 gap-1">
        <button id="tabBtn-overview" onclick="switchTab('overview')" class="py-2 text-xs font-medium rounded-lg transition-all duration-150 bg-[var(--primary)] text-[var(--primary-foreground)] shadow-xs">
          📊 概览透视
        </button>
        <button id="tabBtn-demographics" onclick="switchTab('demographics')" class="py-2 text-xs font-medium rounded-lg transition-all duration-150 text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
          👥 人口画像
        </button>
        <button id="tabBtn-search" onclick="switchTab('search')" class="py-2 text-xs font-medium rounded-lg transition-all duration-150 text-[var(--muted-foreground)] hover:text-[var(--foreground)] flex items-center justify-center gap-1">
          🔍 名单检索
        </button>
      </div>
    </nav>

    <!-- ================= TAB 1: 概览透视 ================= -->
    <div id="tabContent-overview" class="space-y-4">

      <!-- 户型与房源供求 -->
      <section class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-4 shadow-xs">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-semibold flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-blue-500"></span>
            认购户型供求对比
          </h2>
          <span class="text-xs text-[var(--muted-foreground)]">共 931 户</span>
        </div>

        <!-- 比例进度条 -->
        <div class="h-3 w-full bg-[var(--background)] rounded-full overflow-hidden flex mb-2 border border-[var(--border)]">
          <div class="bg-blue-500 h-full transition-all duration-500" style="width: 75.0%;"></div>
          <div class="bg-indigo-500 h-full transition-all duration-500" style="width: 25.0%;"></div>
        </div>

        <div class="grid grid-cols-2 gap-2 text-xs pt-1">
          <div class="bg-[var(--background)] p-2.5 rounded-xl border border-[var(--border)]">
            <div class="flex items-center gap-1.5 text-blue-500 font-medium mb-1">
              <span class="w-2 h-2 rounded-full bg-blue-500"></span>
              两房户型 (68~70㎡)
            </div>
            <div class="text-base font-bold">698 <span class="text-xs font-normal text-[var(--muted-foreground)]">户 (75.0%)</span></div>
            <div class="text-xs text-[var(--muted-foreground)] mt-0.5">共 1,094 人 · 均龄 34.8岁</div>
          </div>
          <div class="bg-[var(--background)] p-2.5 rounded-xl border border-[var(--border)]">
            <div class="flex items-center gap-1.5 text-indigo-500 font-medium mb-1">
              <span class="w-2 h-2 rounded-full bg-indigo-500"></span>
              三房户型 (88~90㎡)
            </div>
            <div class="text-base font-bold">233 <span class="text-xs font-normal text-[var(--muted-foreground)]">户 (25.0%)</span></div>
            <div class="text-xs text-[var(--muted-foreground)] mt-0.5">共 767 人 · 均龄 36.0岁</div>
          </div>
        </div>
      </section>

      <!-- 梯队队列分布卡片 -->
      <section class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-4 shadow-xs">
        <h2 class="text-sm font-semibold mb-3 flex items-center justify-between">
          <span class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
            队列位次分布（点击快速筛选）
          </span>
          <span class="text-xs text-[var(--muted-foreground)] font-normal">先排一队再排二队</span>
        </h2>

        <!-- 两房队列 -->
        <div class="mb-3">
          <div class="text-xs font-medium text-[var(--muted-foreground)] mb-1.5 flex justify-between">
            <span>两房队列 (698户)</span>
            <span>一队入围率最高</span>
          </div>
          <div class="grid grid-cols-3 gap-2">
            <button onclick="filterByQueue('两房', '第一队列')" class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)] hover:border-blue-500 text-left transition-all">
              <div class="text-xs font-medium text-blue-500">第一队列</div>
              <div class="text-sm font-bold mt-0.5">288 <span class="text-xs font-normal text-[var(--muted-foreground)]">户</span></div>
              <div class="text-xs text-[var(--muted-foreground)]">41.3%</div>
            </button>
            <button onclick="filterByQueue('两房', '第二队列')" class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)] hover:border-blue-500 text-left transition-all">
              <div class="text-xs font-medium text-emerald-500">第二队列</div>
              <div class="text-sm font-bold mt-0.5">271 <span class="text-xs font-normal text-[var(--muted-foreground)]">户</span></div>
              <div class="text-xs text-[var(--muted-foreground)]">38.8%</div>
            </button>
            <button onclick="filterByQueue('两房', '第三队列')" class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)] hover:border-blue-500 text-left transition-all">
              <div class="text-xs font-medium text-amber-500">第三队列</div>
              <div class="text-sm font-bold mt-0.5">139 <span class="text-xs font-normal text-[var(--muted-foreground)]">户</span></div>
              <div class="text-xs text-[var(--muted-foreground)]">19.9%</div>
            </button>
          </div>
        </div>

        <!-- 三房队列 -->
        <div>
          <div class="text-xs font-medium text-[var(--muted-foreground)] mb-1.5 flex justify-between">
            <span>三房队列 (233户)</span>
            <span>四队为专科及技能人才</span>
          </div>
          <div class="grid grid-cols-4 gap-1.5">
            <button onclick="filterByQueue('三房', '第一队列')" class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)] hover:border-indigo-500 text-left transition-all">
              <div class="text-xs font-medium text-indigo-500">第一队列</div>
              <div class="text-sm font-bold mt-0.5">28 <span class="text-xs font-normal text-[var(--muted-foreground)]">户</span></div>
              <div class="text-xs text-[var(--muted-foreground)]">12.0%</div>
            </button>
            <button onclick="filterByQueue('三房', '第二队列')" class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)] hover:border-indigo-500 text-left transition-all">
              <div class="text-xs font-medium text-indigo-500">第二队列</div>
              <div class="text-sm font-bold mt-0.5">20 <span class="text-xs font-normal text-[var(--muted-foreground)]">户</span></div>
              <div class="text-xs text-[var(--muted-foreground)]">8.6%</div>
            </button>
            <button onclick="filterByQueue('三房', '第三队列')" class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)] hover:border-indigo-500 text-left transition-all">
              <div class="text-xs font-medium text-indigo-500">第三队列</div>
              <div class="text-sm font-bold mt-0.5">28 <span class="text-xs font-normal text-[var(--muted-foreground)]">户</span></div>
              <div class="text-xs text-[var(--muted-foreground)]">12.0%</div>
            </button>
            <button onclick="filterByQueue('三房', '第四队列')" class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)] hover:border-indigo-500 text-left transition-all">
              <div class="text-xs font-medium text-purple-500">第四队列</div>
              <div class="text-sm font-bold mt-0.5">157 <span class="text-xs font-normal text-[var(--muted-foreground)]">户</span></div>
              <div class="text-xs text-[var(--muted-foreground)]">67.4%</div>
            </button>
          </div>
        </div>
      </section>

      <!-- 人才类型结构 -->
      <section class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-4 shadow-xs">
        <h2 class="text-sm font-semibold mb-3 flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full bg-violet-500"></span>
          人才认定类型构成
        </h2>
        <div class="space-y-2.5 text-xs">
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-medium">全日制本科及以上 (含留学生)</span>
              <span class="text-[var(--muted-foreground)]">870 户 (93.5%)</span>
            </div>
            <div class="h-2 w-full bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-blue-500 h-full rounded-full" style="width: 93.5%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-medium">专科及其他技能人才</span>
              <span class="text-[var(--muted-foreground)]">42 户 (4.5%)</span>
            </div>
            <div class="h-2 w-full bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-purple-500 h-full rounded-full" style="width: 4.5%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-medium">深圳市高层次人才 (杰出/领军)</span>
              <span class="text-[var(--muted-foreground)]">15 户 (1.6%)</span>
            </div>
            <div class="h-2 w-full bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-amber-500 h-full rounded-full" style="width: 1.6%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-medium">特殊政策/满60岁老年人家属</span>
              <span class="text-[var(--muted-foreground)]">4 户 (0.4%)</span>
            </div>
            <div class="h-2 w-full bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-gray-400 h-full rounded-full" style="width: 0.4%;"></div>
            </div>
          </div>
        </div>
      </section>

      <!-- 家庭人口规模 -->
      <section class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-4 shadow-xs">
        <h2 class="text-sm font-semibold mb-3 flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full bg-amber-500"></span>
          家庭人口规模
        </h2>
        <div class="grid grid-cols-5 gap-1.5 text-center">
          <div class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)]">
            <div class="text-xs text-[var(--muted-foreground)]">1人户</div>
            <div class="text-sm font-bold mt-0.5">440</div>
            <div class="text-xs text-[var(--muted-foreground)]">47.3%</div>
          </div>
          <div class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)]">
            <div class="text-xs text-[var(--muted-foreground)]">2人户</div>
            <div class="text-sm font-bold mt-0.5">139</div>
            <div class="text-xs text-[var(--muted-foreground)]">14.9%</div>
          </div>
          <div class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)]">
            <div class="text-xs text-[var(--muted-foreground)]">3人户</div>
            <div class="text-sm font-bold mt-0.5">268</div>
            <div class="text-xs text-[var(--muted-foreground)]">28.8%</div>
          </div>
          <div class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)]">
            <div class="text-xs text-[var(--muted-foreground)]">4人户</div>
            <div class="text-sm font-bold mt-0.5">81</div>
            <div class="text-xs text-[var(--muted-foreground)]">8.7%</div>
          </div>
          <div class="p-2 rounded-xl bg-[var(--background)] border border-[var(--border)]">
            <div class="text-xs text-[var(--muted-foreground)]">5人+</div>
            <div class="text-sm font-bold mt-0.5">3</div>
            <div class="text-xs text-[var(--muted-foreground)]">0.3%</div>
          </div>
        </div>
        <p class="text-xs text-[var(--muted-foreground)] mt-2.5">
          💡 单身人才（1人户）占近一半，主力选择两房第二队列；三口及以上家庭（352户）为三房核心客群。
        </p>
      </section>

    </div>

    <!-- ================= TAB 2: 人口画像 ================= -->
    <div id="tabContent-demographics" class="hidden space-y-4">

      <!-- 原籍来源地分析 -->
      <section class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-4 shadow-xs">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-semibold flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
            主申请人原籍分布 (身份证归属)
          </h2>
          <!-- 切换按钮 -->
          <div class="inline-flex rounded-lg bg-[var(--background)] p-0.5 border border-[var(--border)] text-xs">
            <button id="originBtn-china" onclick="switchOriginView('china')" class="px-2 py-0.5 rounded font-medium bg-[var(--card)] text-[var(--foreground)] shadow-xs">
              全国省份
            </button>
            <button id="originBtn-gd" onclick="switchOriginView('gd')" class="px-2 py-0.5 rounded font-medium text-[var(--muted-foreground)]">
              广东省内
            </button>
          </div>
        </div>

        <!-- 全国省份排行 -->
        <div id="originContent-china" class="space-y-2">
          <div class="text-xs text-[var(--muted-foreground)] mb-2 flex justify-between">
            <span>省份 (Top 10)</span>
            <span>户数 / 占比</span>
          </div>
          <!-- 广东 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium text-emerald-500">1. 广东 (本土)</span>
              <span>438 户 (47.0%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full" style="width: 47.0%;"></div>
            </div>
          </div>
          <!-- 江西 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">2. 江西</span>
              <span>80 户 (8.6%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-blue-500 h-full" style="width: 17.2%;"></div>
            </div>
          </div>
          <!-- 湖南 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">3. 湖南</span>
              <span>74 户 (7.9%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-blue-500 h-full" style="width: 15.9%;"></div>
            </div>
          </div>
          <!-- 湖北 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">4. 湖北</span>
              <span>68 户 (7.3%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-blue-500 h-full" style="width: 14.6%;"></div>
            </div>
          </div>
          <!-- 河南 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">5. 河南</span>
              <span>40 户 (4.3%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-blue-500 h-full" style="width: 8.6%;"></div>
            </div>
          </div>
          <!-- 广西 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">6. 广西</span>
              <span>23 户 (2.5%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-indigo-500 h-full" style="width: 5.0%;"></div>
            </div>
          </div>
          <!-- 黑龙江 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">7. 黑龙江</span>
              <span>22 户 (2.4%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-indigo-500 h-full" style="width: 4.7%;"></div>
            </div>
          </div>
          <!-- 辽宁 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">8. 辽宁</span>
              <span>19 户 (2.0%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-indigo-500 h-full" style="width: 4.1%;"></div>
            </div>
          </div>
          <!-- 安徽 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">9. 安徽</span>
              <span>17 户 (1.8%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-indigo-500 h-full" style="width: 3.7%;"></div>
            </div>
          </div>
          <!-- 吉林 & 福建 -->
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">10. 吉林 / 福建</span>
              <span>各 16 户 (各 1.7%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-indigo-500 h-full" style="width: 3.4%;"></div>
            </div>
          </div>
        </div>

        <!-- 广东省内地级市排行 -->
        <div id="originContent-gd" class="hidden space-y-2">
          <div class="text-xs text-[var(--muted-foreground)] mb-2 flex justify-between">
            <span>城市 (共 438 位省内籍贯)</span>
            <span>户数 / 省内占比</span>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium text-blue-500">1. 深圳 (深二代/早年落户)</span>
              <span>113 户 (25.8%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-blue-500 h-full" style="width: 25.8%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">2. 汕头</span>
              <span>53 户 (12.1%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full" style="width: 12.1%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">3. 揭阳</span>
              <span>51 户 (11.6%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full" style="width: 11.6%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">4. 梅州</span>
              <span>46 户 (10.5%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full" style="width: 10.5%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">5. 汕尾</span>
              <span>38 户 (8.7%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full" style="width: 8.7%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">6. 茂名</span>
              <span>26 户 (5.9%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full" style="width: 5.9%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">7. 河源 / 湛江</span>
              <span>各 18 户 (各 4.1%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full" style="width: 4.1%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">8. 江门</span>
              <span>14 户 (3.2%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full" style="width: 3.2%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span class="font-medium">9. 潮州</span>
              <span>12 户 (2.7%)</span>
            </div>
            <div class="h-2 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full" style="width: 2.7%;"></div>
            </div>
          </div>
        </div>
      </section>

      <!-- 年龄与代际结构 -->
      <section class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-4 shadow-xs">
        <h2 class="text-sm font-semibold mb-3 flex items-center justify-between">
          <span class="flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-blue-500"></span>
            年龄与代际结构 (931人)
          </span>
          <span class="text-xs text-blue-500 font-normal">平均 35.1岁 / 中位数 34岁</span>
        </h2>

        <div class="space-y-2 text-xs">
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-bold text-blue-500">90-94年 (32~36岁 · 绝对主力)</span>
              <span class="font-bold">407 人 (43.7%)</span>
            </div>
            <div class="h-2.5 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-blue-500 h-full rounded-full" style="width: 43.7%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-medium text-emerald-500">95后 (27~31岁 · 青年新锐)</span>
              <span>228 人 (24.5%)</span>
            </div>
            <div class="h-2.5 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-emerald-500 h-full rounded-full" style="width: 24.5%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-medium">85后 (37~41岁 · 资深中坚)</span>
              <span>203 人 (21.8%)</span>
            </div>
            <div class="h-2.5 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-indigo-500 h-full rounded-full" style="width: 21.8%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-medium">80-84年 (42~46岁)</span>
              <span>64 人 (6.9%)</span>
            </div>
            <div class="h-2.5 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-purple-500 h-full rounded-full" style="width: 6.9%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-medium">70后及以前 (>47岁)</span>
              <span>25 人 (2.7%)</span>
            </div>
            <div class="h-2.5 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-gray-400 h-full rounded-full" style="width: 2.7%;"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between mb-1">
              <span class="font-medium">00后 (24~26岁)</span>
              <span>4 人 (0.4%)</span>
            </div>
            <div class="h-2.5 bg-[var(--background)] rounded-full overflow-hidden border border-[var(--border)]">
              <div class="bg-teal-400 h-full rounded-full" style="width: 0.4%;"></div>
            </div>
          </div>
        </div>

        <div class="mt-4 p-3 rounded-xl bg-[var(--background)] border border-[var(--border)] text-xs text-[var(--muted-foreground)] space-y-1">
          <div>🎯 <strong>两房第二队列最年轻</strong>：平均年龄仅 <strong>32.3 岁</strong>，单身青年聚集。</div>
          <div>👶 <strong>最年轻主申</strong>：24 岁（2002 年生）；<strong>最年长主申</strong>：65 岁（1961 年生）。</div>
          <div>📈 <strong>90后（含95后）合计 635 人</strong>，总占比达 <strong>68.2%</strong>。</div>
        </div>
      </section>

    </div>

    <!-- ================= TAB 3: 名单检索 ================= -->
    <div id="tabContent-search" class="hidden space-y-3">

      <!-- 搜索框与过滤器 -->
      <section class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-3 shadow-xs space-y-2.5">
        <div class="relative">
          <input id="searchInput" type="text" placeholder="输入姓名 (如张*) / 认购编号 / 籍贯..."
            oninput="handleSearch()"
            class="w-full pl-9 pr-8 py-2 text-xs rounded-xl bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:outline-hidden focus:border-[var(--primary)] transition-all">
          <span class="absolute left-3 top-2.5 text-xs text-[var(--muted-foreground)]">🔍</span>
          <button id="clearSearchBtn" onclick="clearSearch()" class="hidden absolute right-3 top-2.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]">✕</button>
        </div>

        <!-- 快捷过滤 Chips -->
        <div class="space-y-1.5 text-xs">
          <!-- 户型筛选 -->
          <div class="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5">
            <span class="text-[var(--muted-foreground)] text-xs shrink-0">户型:</span>
            <button onclick="setFilterType('全部')" id="btn-type-all" class="filter-type-btn px-2.5 py-1 rounded-lg text-xs font-medium bg-[var(--primary)] text-[var(--primary-foreground)]">全部</button>
            <button onclick="setFilterType('两房')" id="btn-type-2r" class="filter-type-btn px-2.5 py-1 rounded-lg text-xs font-medium bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)]">两房 (698)</button>
            <button onclick="setFilterType('三房')" id="btn-type-3r" class="filter-type-btn px-2.5 py-1 rounded-lg text-xs font-medium bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)]">三房 (233)</button>
          </div>

          <!-- 队列筛选 -->
          <div class="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5">
            <span class="text-[var(--muted-foreground)] text-xs shrink-0">队列:</span>
            <button onclick="setFilterQueue('全部')" id="btn-q-all" class="filter-q-btn px-2 py-0.5 rounded-md text-xs font-medium bg-[var(--primary)] text-[var(--primary-foreground)]">全部</button>
            <button onclick="setFilterQueue('第一队列')" id="btn-q-1" class="filter-q-btn px-2 py-0.5 rounded-md text-xs font-medium bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)]">一队</button>
            <button onclick="setFilterQueue('第二队列')" id="btn-q-2" class="filter-q-btn px-2 py-0.5 rounded-md text-xs font-medium bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)]">二队</button>
            <button onclick="setFilterQueue('第三队列')" id="btn-q-3" class="filter-q-btn px-2 py-0.5 rounded-md text-xs font-medium bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)]">三队</button>
            <button onclick="setFilterQueue('第四队列')" id="btn-q-4" class="filter-q-btn px-2 py-0.5 rounded-md text-xs font-medium bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)]">四队</button>
          </div>
        </div>

        <div class="flex items-center justify-between text-xs text-[var(--muted-foreground)] pt-1 border-t border-[var(--border)]">
          <span id="resultCountText">共 931 户家庭</span>
          <span class="text-xs">按选房序号升序排列</span>
        </div>
      </section>

      <!-- 搜索结果列表 -->
      <div id="applicantListContainer" class="space-y-2.5">
        <!-- JS 动态注入卡片 -->
      </div>

      <!-- 加载更多按钮 -->
      <div id="loadMoreBox" class="text-center pt-2">
        <button onclick="loadMore()" id="loadMoreBtn" class="w-full py-2.5 text-xs font-medium rounded-xl bg-[var(--card)] border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--background)] transition-all">
          加载更多名单...
        </button>
      </div>

    </div>

  </div>

  <!-- 数据注入与前端逻辑 -->
  <script>
    const ALL_DATA = {raw_data};
    let currentFilterType = '全部';
    let currentFilterQueue = '全部';
    let currentSearchText = '';
    let filteredList = [...ALL_DATA];
    let pageSize = 25;
    let currentPage = 1;

    // 选项卡切换
    function switchTab(tabId) {{
      const tabs = ['overview', 'demographics', 'search'];
      tabs.forEach(t => {{
        const btn = document.getElementById(`tabBtn-${{t}}`);
        const content = document.getElementById(`tabContent-${{t}}`);
        if (t === tabId) {{
          btn.className = "py-2 text-xs font-medium rounded-lg transition-all duration-150 bg-[var(--primary)] text-[var(--primary-foreground)] shadow-xs";
          content.classList.remove('hidden');
        }} else {{
          btn.className = "py-2 text-xs font-medium rounded-lg transition-all duration-150 text-[var(--muted-foreground)] hover:text-[var(--foreground)]";
          content.classList.add('hidden');
        }}
      }});
      if (tabId === 'search') {{
        renderList();
      }}
    }}

    // 生源地图表切换
    function switchOriginView(view) {{
      const chinaBtn = document.getElementById('originBtn-china');
      const gdBtn = document.getElementById('originBtn-gd');
      const chinaContent = document.getElementById('originContent-china');
      const gdContent = document.getElementById('originContent-gd');

      if (view === 'china') {{
        chinaBtn.className = "px-2 py-0.5 rounded font-medium bg-[var(--card)] text-[var(--foreground)] shadow-xs";
        gdBtn.className = "px-2 py-0.5 rounded font-medium text-[var(--muted-foreground)]";
        chinaContent.classList.remove('hidden');
        gdContent.classList.add('hidden');
      }} else {{
        gdBtn.className = "px-2 py-0.5 rounded font-medium bg-[var(--card)] text-[var(--foreground)] shadow-xs";
        chinaBtn.className = "px-2 py-0.5 rounded font-medium text-[var(--muted-foreground)]";
        gdContent.classList.remove('hidden');
        chinaContent.classList.add('hidden');
      }}
    }}

    // 快捷从概览跳转到检索
    function filterByQueue(houseType, queue) {{
      currentFilterType = houseType;
      currentFilterQueue = queue;
      updateFilterButtons();
      switchTab('search');
      applyFilters();
    }}

    function setFilterType(type) {{
      currentFilterType = type;
      updateFilterButtons();
      applyFilters();
    }}

    function setFilterQueue(queue) {{
      currentFilterQueue = queue;
      updateFilterButtons();
      applyFilters();
    }}

    function updateFilterButtons() {{
      const typeMap = {{
        '全部': 'btn-type-all',
        '两房': 'btn-type-2r',
        '三房': 'btn-type-3r'
      }};
      Object.keys(typeMap).forEach(k => {{
        const btn = document.getElementById(typeMap[k]);
        if (btn) {{
          if (k === currentFilterType) {{
            btn.className = "filter-type-btn px-2.5 py-1 rounded-lg text-xs font-medium bg-[var(--primary)] text-[var(--primary-foreground)]";
          }} else {{
            btn.className = "filter-type-btn px-2.5 py-1 rounded-lg text-xs font-medium bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)]";
          }}
        }}
      }});

      const qMap = {{
        '全部': 'btn-q-all',
        '第一队列': 'btn-q-1',
        '第二队列': 'btn-q-2',
        '第三队列': 'btn-q-3',
        '第四队列': 'btn-q-4'
      }};
      Object.keys(qMap).forEach(k => {{
        const btn = document.getElementById(qMap[k]);
        if (btn) {{
          if (k === currentFilterQueue) {{
            btn.className = "filter-q-btn px-2 py-0.5 rounded-md text-xs font-medium bg-[var(--primary)] text-[var(--primary-foreground)]";
          }} else {{
            btn.className = "filter-q-btn px-2 py-0.5 rounded-md text-xs font-medium bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)]";
          }}
        }}
      }});
    }}

    function handleSearch() {{
      const input = document.getElementById('searchInput');
      const clearBtn = document.getElementById('clearSearchBtn');
      currentSearchText = input.value.trim().toLowerCase();
      if (currentSearchText) {{
        clearBtn.classList.remove('hidden');
      }} else {{
        clearBtn.classList.add('hidden');
      }}
      applyFilters();
    }}

    function clearSearch() {{
      const input = document.getElementById('searchInput');
      input.value = '';
      currentSearchText = '';
      document.getElementById('clearSearchBtn').classList.add('hidden');
      applyFilters();
    }}

    function applyFilters() {{
      filteredList = ALL_DATA.filter(item => {{
        if (currentFilterType !== '全部' && item.t !== currentFilterType) return false;
        if (currentFilterQueue !== '全部' && item.q !== currentFilterQueue) return false;
        if (currentSearchText) {{
          const matchName = item.n.toLowerCase().includes(currentSearchText);
          const matchCode = item.c.toLowerCase().includes(currentSearchText);
          const matchOrigin = item.o.toLowerCase().includes(currentSearchText);
          const matchMembers = item.m.toLowerCase().includes(currentSearchText);
          const matchId = item.id.includes(currentSearchText);
          if (!matchName && !matchCode && !matchOrigin && !matchMembers && !matchId) return false;
        }}
        return true;
      }});

      currentPage = 1;
      document.getElementById('resultCountText').innerText = `匹配到 ${{filteredList.length}} 户家庭`;
      renderList();
    }}

    function renderList() {{
      const container = document.getElementById('applicantListContainer');
      const loadMoreBox = document.getElementById('loadMoreBox');
      const loadMoreBtn = document.getElementById('loadMoreBtn');

      if (currentPage === 1) {{
        container.innerHTML = '';
      }}

      if (filteredList.length === 0) {{
        container.innerHTML = `
          <div class="p-8 text-center bg-[var(--card)] border border-[var(--border)] rounded-2xl text-[var(--muted-foreground)] text-xs">
            未检索到符合条件的申请家庭
          </div>
        `;
        loadMoreBox.classList.add('hidden');
        return;
      }}

      const currentItems = filteredList.slice(0, currentPage * pageSize);

      let html = '';
      currentItems.forEach((item, idx) => {{
        const isTwo = item.t === '两房';
        const badgeColor = isTwo ? 'text-blue-500 bg-blue-500/10 border-blue-500/20' : 'text-indigo-500 bg-indigo-500/10 border-indigo-500/20';
        
        html += `
          <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl p-3 shadow-xs space-y-2">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-[var(--background)] border border-[var(--border)] text-xs font-bold text-[var(--foreground)]">
                  ${{item.s}}
                </span>
                <span class="font-bold text-sm text-[var(--foreground)]">${{item.n}}</span>
                <span class="text-xs text-[var(--muted-foreground)]">${{item.a}}岁 · ${{item.o}}</span>
              </div>
              <span class="px-2 py-0.5 rounded text-xs font-medium border ${{badgeColor}}">
                ${{item.t}} · ${{item.q}}
              </span>
            </div>

            <div class="grid grid-cols-2 gap-2 text-xs text-[var(--muted-foreground)] bg-[var(--background)]/60 p-2 rounded-lg border border-[var(--border)]">
              <div>编号: <span class="text-[var(--foreground)] font-mono">${{item.c}}</span></div>
              <div>证件: <span class="text-[var(--foreground)] font-mono">${{item.id}}</span></div>
              <div>家庭: <span class="text-[var(--foreground)] font-medium">${{item.fs}}人户</span></div>
              <div>人才: <span class="text-[var(--foreground)]">${{item.tl}}</span></div>
            </div>

            <div class="text-xs text-[var(--muted-foreground)] pt-0.5 flex items-start gap-1">
              <span class="shrink-0 text-gray-400">成员:</span>
              <span class="text-[var(--foreground)] line-clamp-1">${{item.m}}</span>
            </div>
          </div>
        `;
      }});

      container.innerHTML = html;

      if (currentItems.length < filteredList.length) {{
        loadMoreBox.classList.remove('hidden');
        loadMoreBtn.innerText = `加载更多 (${{currentItems.length}} / ${{filteredList.length}})`;
      }} else {{
        loadMoreBox.classList.add('hidden');
      }}
    }}

    function loadMore() {{
      currentPage++;
      renderList();
    }}

    // 初始化渲染
    window.addEventListener('DOMContentLoaded', () => {{
      renderList();
    }});
  </script>
</body>
</html>
"""

# 写入当前工程目录
with open(OUTPUT_LOCAL, "w", encoding="utf-8") as f:
    f.write(html_template)
print(f"Generated: {OUTPUT_LOCAL}")

# 写入 Artifact 目录
os.makedirs(os.path.dirname(OUTPUT_ARTIFACT), exist_ok=True)
with open(OUTPUT_ARTIFACT, "w", encoding="utf-8") as f:
    f.write(html_template)
print(f"Generated Artifact: {OUTPUT_ARTIFACT}")
