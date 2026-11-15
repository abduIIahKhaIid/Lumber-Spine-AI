import torch.nn as nn
import torch.nn.functional as F


# HardSwish Activation
class HardSwish(nn.Module):
    def forward(self, x):
        return x * F.hardtanh(x + 3, 0.0, 6.0, inplace=True) / 6.0


# HardSigmoid (for Gated Attention)
class HardSigmoid(nn.Module):
    def forward(self, x):
        return F.hardtanh(x + 3, 0.0, 6.0, inplace=True) / 6.0


# Gated Attention 3D
class GatedAttention3D(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.gate = nn.Sequential(
            nn.Linear(channels, channels), nn.Tanh(), nn.Linear(channels, channels), nn.Sigmoid()
        )

    def forward(self, x):
        gate_weights = self.gate(x)
        return x * gate_weights


# Squeeze-and-Excitation for 3D
class SEBlock3D(nn.Module):
    def __init__(self, channels, reduction=4):
        super().__init__()
        self.pool = nn.AdaptiveAvgPool3d(1)
        self.fc = nn.Sequential(
            nn.Linear(channels, channels // reduction, bias=False),
            nn.ReLU(),
            nn.Linear(channels // reduction, channels, bias=False),
            HardSigmoid(),
        )

    def forward(self, x):
        b, c, _, _, _ = x.shape
        y = self.pool(x).view(b, c)
        y = self.fc(y).view(b, c, 1, 1, 1)
        return x * y


# MobileNetV3 Block for 3D with Dropout
class MobileNetV3Block3D(nn.Module):
    def __init__(
        self, in_channels, out_channels, expansion, stride, use_se, activation="HS", dropout=0.1
    ):
        super().__init__()
        self.use_residual = stride == 1 and in_channels == out_channels
        mid_channels = int(in_channels * expansion)

        act_fn = HardSwish() if activation == "HS" else nn.ReLU()

        self.expand = (
            nn.Sequential(
                nn.Conv3d(in_channels, mid_channels, kernel_size=1, bias=False),
                nn.BatchNorm3d(mid_channels),
                act_fn,
            )
            if expansion != 1
            else nn.Identity()
        )

        self.depthwise = nn.Sequential(
            nn.Conv3d(
                mid_channels,
                mid_channels,
                kernel_size=3,
                stride=stride,
                padding=1,
                groups=mid_channels,
                bias=False,
            ),
            nn.BatchNorm3d(mid_channels),
            act_fn,
        )

        self.se = SEBlock3D(mid_channels) if use_se else nn.Identity()

        self.project = nn.Sequential(
            nn.Conv3d(mid_channels, out_channels, kernel_size=1, bias=False),
            nn.BatchNorm3d(out_channels),
        )

        self.dropout = nn.Dropout3d(p=dropout)

    def forward(self, x):
        identity = x
        out = self.expand(x)
        out = self.depthwise(out)
        out = self.se(out)
        out = self.project(out)
        out = self.dropout(out)
        if self.use_residual:
            out = out + identity
        return out


# Full Model with FC layer and Gated Attention
class Spine3DMobileNetV3(nn.Module):
    def __init__(self, in_channels=1, num_classes=3, hidden_dim=1024, condition="scs", dropout=0.3):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv3d(in_channels, 16, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm3d(16),
            HardSwish(),
        )

        self.blocks = nn.Sequential(
            MobileNetV3Block3D(16, 16, expansion=1, stride=1, use_se=False, activation="RE"),
            MobileNetV3Block3D(16, 24, expansion=4, stride=2, use_se=False, activation="RE"),
            MobileNetV3Block3D(24, 24, expansion=3, stride=1, use_se=False, activation="RE"),
            MobileNetV3Block3D(24, 40, expansion=3, stride=2, use_se=True, activation="HS"),
            MobileNetV3Block3D(40, 40, expansion=3, stride=1, use_se=True, activation="HS"),
            MobileNetV3Block3D(40, 80, expansion=6, stride=2, use_se=False, activation="HS"),
            MobileNetV3Block3D(80, 80, expansion=2.5, stride=1, use_se=False, activation="HS"),
            MobileNetV3Block3D(80, 112, expansion=6, stride=1, use_se=True, activation="HS"),
            MobileNetV3Block3D(112, 160, expansion=6, stride=2, use_se=True, activation="HS"),
            MobileNetV3Block3D(160, 160, expansion=6, stride=1, use_se=True, activation="HS"),
        )

        self.pool = nn.AdaptiveAvgPool3d(1)
        self.gated_attn = GatedAttention3D(160)

        self.fc = nn.Sequential(nn.Linear(160, hidden_dim), HardSwish(), nn.Dropout(p=dropout))

        if condition == "scs":
            self.l1 = nn.Linear(hidden_dim, num_classes)
            self.l2 = nn.Linear(hidden_dim, num_classes)
            self.l3 = nn.Linear(hidden_dim, num_classes)
            self.l4 = nn.Linear(hidden_dim, num_classes)
            self.l5 = nn.Linear(hidden_dim, num_classes)
        else:
            self.ll1 = nn.Linear(hidden_dim, num_classes)
            self.ll2 = nn.Linear(hidden_dim, num_classes)
            self.ll3 = nn.Linear(hidden_dim, num_classes)
            self.ll4 = nn.Linear(hidden_dim, num_classes)
            self.ll5 = nn.Linear(hidden_dim, num_classes)
            self.rl1 = nn.Linear(hidden_dim, num_classes)
            self.rl2 = nn.Linear(hidden_dim, num_classes)
            self.rl3 = nn.Linear(hidden_dim, num_classes)
            self.rl4 = nn.Linear(hidden_dim, num_classes)
            self.rl5 = nn.Linear(hidden_dim, num_classes)

        self.condition = condition

    def forward(self, x):
        x = x.unsqueeze(1)  # (B, 1, D, H, W)
        x = self.stem(x)
        x = self.blocks(x)
        x = self.pool(x).flatten(1)
        x = self.gated_attn(x)
        x = self.fc(x)

        if self.condition == "scs":
            return {
                "L1/L2": self.l1(x).sigmoid(),
                "L2/L3": self.l2(x).sigmoid(),
                "L3/L4": self.l3(x).sigmoid(),
                "L4/L5": self.l4(x).sigmoid(),
                "L5/S1": self.l5(x).sigmoid(),
            }

        else:
            return {
                "left_L1/L2": self.ll1(x).sigmoid(),
                "left_L2/L3": self.ll2(x).sigmoid(),
                "left_L3/L4": self.ll3(x).sigmoid(),
                "left_L4/L5": self.ll4(x).sigmoid(),
                "left_L5/S1": self.ll5(x).sigmoid(),
                "right_L1/L2": self.rl1(x).sigmoid(),
                "right_L2/L3": self.rl2(x).sigmoid(),
                "right_L3/L4": self.rl3(x).sigmoid(),
                "right_L4/L5": self.rl4(x).sigmoid(),
                "right_L5/S1": self.rl5(x).sigmoid(),
            }
