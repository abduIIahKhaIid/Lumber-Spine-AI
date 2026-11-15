"""MedicalNet 3D ResNet10 with Stage 1 normalized XYZ regression heads."""

import torch.nn as nn


class MedicalNetResNet10XYZ(nn.Module):
    def __init__(self, condition="scs", pretrained=False):
        super().__init__()
        from monai.networks.nets import resnet10

        if condition not in ("scs", "nfn", "ss"):
            raise ValueError(f"Unsupported Stage 1 condition: {condition}")
        self.encoder = resnet10(
            pretrained=pretrained,
            spatial_dims=3,
            n_input_channels=1,
            conv1_t_stride=2,
            shortcut_type="B",
            bias_downsample=False,
            feed_forward=False,
        )
        self.features = nn.Sequential(nn.Linear(512, 256), nn.ReLU(), nn.Dropout(0.3))
        levels = ("L1/L2", "L2/L3", "L3/L4", "L4/L5", "L5/S1")
        self.keys = (
            levels
            if condition == "scs"
            else tuple(f"{side}_{level}" for side in ("left", "right") for level in levels)
        )
        self.heads = nn.ModuleDict({key.replace("/", "_"): nn.Linear(256, 3) for key in self.keys})

    def forward(self, x):
        features = self.encoder(x.unsqueeze(1))
        features = self.features(features)
        return {key: self.heads[key.replace("/", "_")](features).sigmoid() for key in self.keys}
