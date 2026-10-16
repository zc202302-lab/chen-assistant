"""Optional offline OCR adapters. Preserve model output and geometry for auditing."""
import json
from pathlib import Path


def reading_order(lines, width):
    """Conservative two-column ordering; spanning lines delimit vertical zones.

    Geometry and original detector order are retained separately. This is not a
    recipe parser and does not infer or correct any ingredient/quantity text.
    """
    if not lines:
        return []
    def bounds(line):
        xs=[p[0] for p in line[0]];ys=[p[1] for p in line[0]]
        return min(xs),min(ys),max(xs),max(ys)
    indexed=[(i,bounds(line)) for i,line in enumerate(lines)]
    seam=width/2
    left=[item for item in indexed if item[1][2]<=seam]
    right=[item for item in indexed if item[1][0]>=seam]
    spanning=[item for item in indexed if item not in left and item not in right]
    if min(len(left),len(right))<4 or len(spanning)>len(lines)*.25:
        return list(range(len(lines)))
    order=[]
    remaining=left+right
    for index,box in sorted(spanning,key=lambda item:item[1][1]):
        above=[item for item in remaining if (item[1][1]+item[1][3])/2<box[1]]
        for column in (left,right):
            order.extend(i for i,b in sorted(above,key=lambda item:(item[1][1],item[1][0])) if (i,b) in column)
        remaining=[item for item in remaining if item not in above]
        order.append(index)
    for column in (left,right):
        order.extend(i for i,b in sorted(remaining,key=lambda item:(item[1][1],item[1][0])) if (i,b) in column)
    assert sorted(order)==list(range(len(lines)))
    return order


class RapidReader:
    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self.engine=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1)

    def read(self, image_path, width, audit_path):
        lines,_=self.engine(str(image_path),text_score=0.0)
        lines=lines or []
        order=reading_order(lines,width)
        payload={'engine':'rapidocr-onnxruntime','width':width,
                 'lines':lines,'reading_order':order,
                 'warning':'OCR未人工逐字核对，置信度不是准确率；用量以原页为准'}
        Path(audit_path).parent.mkdir(parents=True,exist_ok=True)
        Path(audit_path).write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
        return '\n'.join(lines[index][1] for index in order)
