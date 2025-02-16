from model.convnet import LitConvNet
import torch

lit_model = LitConvNet()

fake_data = torch.rand(1, 1, 15, 15)
output = lit_model.model(fake_data)
print(output)

torch.onnx.export(
    lit_model.model,
    (fake_data,),
    "../model.onnx",
    input_names=["inputs"],
    output_names=["value_head"],
)