const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
        ShadingType, PageNumber, PageBreak } = require('docx');
const fs = require('fs');

const border = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };

function createEmphasisBlock(text, color = 'D5E8F0') {
  return new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: '2E75B6', space: 1 } },
    shading: { fill: color, type: ShadingType.CLEAR },
    margins: { top: 120, bottom: 120, left: 180, right: 180 },
    children: [new TextRun({ text, bold: true, size: 26, color: '1E4D7B' })]
  });
}

function createTable(data, hasHeader = true) {
  const cols = data[0].length;
  const colWidth = Math.floor(9360 / cols);
  const borders = { top: border, bottom: border, left: border, right: border };
  
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: Array(cols).fill(colWidth),
    rows: data.map((row, idx) => new TableRow({
      children: row.map(cell => new TableCell({
        borders,
        width: { size: colWidth, type: WidthType.DXA },
        shading: hasHeader && idx === 0 ? { fill: '2E75B6', type: ShadingType.CLEAR } : undefined,
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({
            text: cell,
            bold: hasHeader && idx === 0,
            color: hasHeader && idx === 0 ? 'FFFFFF' : '333333',
            size: 24
          })]
        })]
      }))
    }))
  });
}

const coverSection = {
  properties: {
    page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
  },
  children: [
    new Paragraph({
      children: [new TextRun({ text: 'RAG-Anything', size: 48, bold: true, color: '2E75B6' })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 1440, after: 720 }
    }),
    new Paragraph({
      children: [new TextRun({ text: '全功能多模态文档智能分析系统', size: 32, color: '365F91' })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 1440 }
    }),
    new Paragraph({
      children: [new TextRun({ text: '产品演示演讲稿', size: 28, italic: true, color: '666666' })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 1440 }
    }),
    new Paragraph({
      children: [new TextRun({ text: '—— 让您的文档真正“活”起来', size: 24, color: '999999' })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 720 }
    }),
    new Paragraph({
      children: [new TextRun({ text: '2026年', size: 22, color: '999999' })],
      alignment: AlignmentType.CENTER
    }),
    new Paragraph({ children: [new PageBreak()] })
  ]
};

const contentSection = {
  properties: {
    page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
  },
  headers: {
    default: new Header({ children: [new Paragraph({
      border: { bottom: { style: BorderStyle.SINGLE, size: 1, color: 'E0E0E0' } },
      children: [new TextRun({ text: 'RAG-Anything 产品演示', size: 20, color: '666666' })]
    })] })
  },
  footers: {
    default: new Footer({ children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: '第 ' }), new TextRun({ children: [PageNumber.CURRENT] }), new TextRun({ text: ' 页' })]
    })] })
  },
  children: [
    new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('一、开场：直击痛点')] }),
    new Paragraph({ children: [new TextRun({ text: '各位领导、各位同事，大家好！', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '今天站在这里，我想先问大家几个问题——', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '1. 你们公司有没有堆积如山的 PDF 文件、Word 文档、Excel 表格？', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '2. 当你需要找一个关键数据时，是不是经常要翻遍几十份文档？', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '3. 看到满页的图表和公式，是不是经常觉得“字都认识，放一起就看不懂”？', size: 26 })] }),
    createEmphasisBlock('这就是我们今天要解决的问题——让你的文档真正“活”起来，让机器替你读懂所有内容。'),

    new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('二、引出产品：一句话定义')] }),
    new Paragraph({ children: [new TextRun({ text: '今天我要给大家介绍的这款产品，叫做 RAG-Anything。', size: 26 })] }),
    createEmphasisBlock('一句话来说，它就是一个——能看懂图片、表格、公式的超级智能文档助手。'),
    new Paragraph({ children: [new TextRun({ text: '想象一下，你上传一份几十页的财务报表，它不仅能理解文字内容，还能看懂里面的折线图、柱状图、复杂表格，甚至是数学公式。然后你问它任何问题，它都能从这些多模态内容中找到答案。', size: 26 })] }),

    new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('三、架构讲解：用流程化语言讲清楚')] }),
    new Paragraph({ children: [new TextRun({ text: '接下来，我用一个简单的流程，给大家讲清楚它是怎么工作的。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('第一步：输入——任何格式都能吃')] }),
    new Paragraph({ children: [new TextRun({ text: '我们的系统支持几乎所有常见文档格式：PDF、Word、Excel、PowerPoint、图片（JPG、PNG、BMP、TIFF）、文本文件、Markdown。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('第二步：解析——把文档拆开看懂')] }),
    new Paragraph({ children: [new TextRun({ text: '系统会像一个专业的文档分析师一样，把文档拆解成不同类型的内容：文字内容直接提取，图片识别内容，表格理解结构和数据关系，公式解析数学含义。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('第三步：理解——构建知识图谱')] }),
    new Paragraph({ children: [new TextRun({ text: '系统不仅是简单地读取内容，它还会从文本中提取实体（比如公司名、人名、产品名），识别实体之间的关系（比如“属于”、“合作”、“投资”），把这些信息组织成一个知识图谱。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('第四步：检索——快速找到答案')] }),
    new Paragraph({ children: [new TextRun({ text: '当你提出问题时，系统会分析你的问题意图，在知识图谱中进行图遍历，在向量数据库中进行相似度检索，综合这两种方式，给出最精准的答案。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('第五步：回答——VLM增强让答案更精准')] }),
    createEmphasisBlock('特别要提到的是，我们采用了 VLM（视觉语言模型）增强技术。当检索结果中包含图片时，系统会自动调用视觉模型去“看”这张图，理解图中的内容，然后把图像理解的结果融入到最终的回答中。'),

    new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('四、优势对比：我们和传统方案有什么不同？')] }),
    createTable([
      ['对比维度', '传统方案', 'RAG-Anything'],
      ['内容理解', '只能处理纯文本', '支持图片、表格、公式、图表'],
      ['上下文感知', '孤立处理每段文字', '理解内容之间的关联和上下文'],
      ['查询方式', '关键词匹配，结果死板', '支持自然语言问答，理解意图'],
      ['图像分析', '完全忽略图像内容', 'VLM增强，自动分析图片中的信息'],
      ['知识关联', '无知识图谱，信息碎片化', '构建知识图谱，理解实体关系'],
    ]),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('优势一：真正的多模态理解')] }),
    new Paragraph({ children: [new TextRun({ text: '传统方案处理文档时，遇到图片、表格、公式就“失明”了。但我们的系统能看懂所有类型的内容。不管是财务报表的复杂表格，还是技术文档的数学公式，甚至是流程图、架构图，它都能理解。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('优势二：上下文感知能力')] }),
    new Paragraph({ children: [new TextRun({ text: '我们的系统不是简单地把文档切成小块，而是会理解内容之间的上下文关系。比如，当它看到“图3-2”这个引用时，会自动找到对应的图表，并把图表的内容纳入理解范围。', size: 26 })] }),

    new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('五、应用场景：这东西到底能用来干什么？')] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('场景一：金融行业——财务报表智能分析')] }),
    new Paragraph({ children: [new TextRun({ text: '痛点：每年的财务报表有几百页，包含大量的表格、图表、附注。分析师需要花大量时间阅读和整理。', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '解决方案：上传年报后，系统自动构建财务知识图谱。可以问“2024年净利润同比增长多少？”，系统会自动找到相关表格和文字，给出精准答案。', size: 26 })] }),
    createEmphasisBlock('价值：分析师的工作效率提升 50% 以上。'),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('场景二：技术部门——API文档智能问答')] }),
    new Paragraph({ children: [new TextRun({ text: '痛点：技术文档越来越多，开发人员找一个接口的用法可能要翻几十页。', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '解决方案：上传API文档后，系统自动理解接口之间的调用关系。可以问“用户登录接口需要哪些参数？”，系统会直接给出接口定义、参数说明、示例代码。', size: 26 })] }),
    createEmphasisBlock('价值：开发人员查找文档的时间减少 70%。'),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('场景三：学术研究——论文智能检索')] }),
    new Paragraph({ children: [new TextRun({ text: '痛点：学术论文中有大量的公式、图表、实验数据，传统检索工具很难理解这些内容。', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '解决方案：上传论文库后，系统自动提取论文中的公式、图表、实验结果。可以问“图5的实验结果说明了什么？”，系统会综合文字和图表内容，给出完整回答。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('场景四：企业知识库——内部文档智能问答')] }),
    new Paragraph({ children: [new TextRun({ text: '痛点：企业内部有大量的规章制度、操作手册、培训文档，但员工很难快速找到需要的信息。', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '解决方案：把所有内部文档导入系统。员工可以用自然语言提问：“报销流程是怎样的？”，系统会自动找到相关制度，并给出步骤说明。', size: 26 })] }),

    new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('六、收尾：总结与下一步行动')] }),
    new Paragraph({ children: [new TextRun({ text: '最后，我想总结一下 RAG-Anything 能给您带来什么价值：', size: 26 })] }),
    createEmphasisBlock('核心价值：让你的文档资产真正“活”起来，变成可查询、可理解的知识。'),
    
    new Paragraph({ children: [new TextRun({ text: '具体收益：', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '• 效率提升：查找信息的时间大幅减少', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '• 决策加速：从文档中获取洞察的速度更快', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '• 知识沉淀：企业知识不再随人员流动而流失', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '• 成本降低：减少人工整理文档的人力成本', size: 26 })] }),
    
    new Paragraph({ children: [new TextRun({ text: '今天的演示就到这里。如果您感兴趣，我们可以安排定制化演示、提供免费试用、深入讨论集成方案。', size: 26 })] }),
    new Paragraph({ children: [new TextRun({ text: '感谢大家的时间！谢谢！', size: 26 })] }),

    new Paragraph({ children: [new PageBreak()] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('附录：常见问题及回答')] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('Q1：系统支持哪些文档格式？')] }),
    new Paragraph({ children: [new TextRun({ text: '支持 PDF、Word（.doc/.docx）、Excel（.xls/.xlsx）、PowerPoint（.ppt/.pptx）、图片（JPG/PNG/BMP/TIFF/GIF）、文本文件、Markdown 等。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('Q2：部署方式是怎样的？')] }),
    new Paragraph({ children: [new TextRun({ text: '支持两种部署方式：本地部署（安装在您的服务器上，数据完全自主可控）和云端服务（通过 API 调用，快速接入）。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('Q3：数据安全如何保证？')] }),
    new Paragraph({ children: [new TextRun({ text: '本地部署模式下，所有数据都存储在您自己的服务器上；支持加密传输和存储；可以对接您现有的身份认证系统。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('Q4：系统的响应速度如何？')] }),
    new Paragraph({ children: [new TextRun({ text: '文档解析：一份50页的PDF大约需要1-2分钟；查询响应：大部分查询在1-3秒内返回结果；支持批量处理，可以并行处理多个文档。', size: 26 })] }),
    
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('Q5：如何与现有系统集成？')] }),
    new Paragraph({ children: [new TextRun({ text: '提供完整的 API 接口，可以与您的 OA 系统、知识库系统、CRM 系统等无缝对接。', size: 26 })] }),
  ]
};

const doc = new Document({
  styles: {
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 36, bold: true, font: 'Arial', color: '2E75B6' },
        paragraph: { spacing: { before: 240, after: 180 }, outlineLevel: 0, alignment: AlignmentType.CENTER } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 32, bold: true, font: 'Arial', color: '365F91' },
        paragraph: { spacing: { before: 200, after: 140 }, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 28, bold: true, font: 'Arial', color: '4A7BC4' },
        paragraph: { spacing: { before: 160, after: 100 }, outlineLevel: 2 } },
    ]
  },
  sections: [coverSection, contentSection]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync('c:/Users/98014/RAG-Anything/产品演示演讲稿_专业版.docx', buffer);
  console.log('文档生成成功！');
}).catch(err => {
  console.error('生成文档时出错:', err);
});
