"""Shared severity classifier architecture for both scan workflows."""

import timm
import torch.nn as nn


class GatedAttention(nn.Module):
    def __init__(self, in_channels):
        super().__init__()
        self.attn = nn.Sequential(
            nn.Conv2d(in_channels, in_channels // 2, kernel_size=1),
            nn.ReLU(),
            nn.Conv2d(in_channels // 2, in_channels, kernel_size=1),
            nn.Sigmoid(),
        )
        self.residual = nn.Conv2d(in_channels, in_channels, kernel_size=3, padding=1)

    def forward(self, x):
        gate = self.attn(x)
        res = self.residual(x)
        return x + gate * res


class SeverityNet(nn.Module):
    def __init__(self, model_name="mobilenetv3_small_100", num_classes=3):
        super().__init__()
        self.base = timm.create_model(model_name, pretrained=False, in_chans=3, num_classes=0)
        in_features = self.base.num_features

        self.attn = GatedAttention(in_features)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.dropout = nn.Dropout(0.3)

        self.classifier = nn.Sequential(
            nn.Linear(in_features, 1024),
            nn.ReLU(),
            nn.Dropout(0.4),
            nn.Linear(1024, num_classes),
        )

    def forward(self, x):
        x = self.base.forward_features(x)
        x = self.attn(x)
        x = self.pool(x).flatten(1)
        x = self.dropout(x)
        x = self.classifier(x)
        return x
