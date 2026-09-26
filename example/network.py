# ./example/network.py
import copy

from core.model import Fact, KnowledgeBase, Rule

__name__ = "network_troubleshooting"

def _has(name):
    """条件：工作内存中存在指定事实。函数名带上事实名，便于静态追踪推理链。"""

    def condition(wm):
        return any(f.name == name for f in wm.facts)

    condition.__name__ = f"has_{name}"
    condition.__qualname__ = f"has_{name}"
    return condition


_kb = KnowledgeBase()

def get_kb():
    return copy.deepcopy(_kb)

# ===================== 物理层 =====================
_kb.add_rule(Rule("PHY-001 网线/物理链路完全断开", [_has("wire_connected"), _has("link_down"), _has("ping_gateway_fail")], Fact("cable_broken"), 100))          # fix_check_cable, fix_check_switch_port_led
_kb.add_rule(Rule("PHY-002 接口被管理性关闭(shutdown)", [_has("wire_connected"), _has("link_down"), _has("switch_port_shutdown")], Fact("port_admin_down"), 100))   # fix_no_shutdown
_kb.add_rule(Rule("PHY-005 双工模式不匹配", [_has("wire_connected"), _has("late_collision"), _has("high_latency")], Fact("duplex_mismatch"), 50))                   # fix_force_duplex_full
_kb.add_rule(Rule("PHY-006 网卡已被禁用", [_has("wire_connected"), _has("no_network_adapter"), _has("no_ip_address")], Fact("nic_disabled"), 100))                  # fix_enable_nic
_kb.add_rule(Rule("PHY-007 网卡驱动异常", [_has("wire_connected"), _has("nic_driver_error"), _has("link_down")], Fact("driver_fault"), 100))                        # fix_reinstall_nic_driver

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("PHY-101 中间事实：物理层链路不稳定", [_has("wire_connected"), _has("link_flapping")], Fact("physical_link_unstable"), 60))                              # 下游：以太网链路质量
# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("PHY-102 中间事实：以太网链路质量异常", [_has("wire_connected"), _has("physical_link_unstable"), _has("crc_error")], Fact("ethernet_quality_issue"), 60))  # 下游：光模块 / 线缆
# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("PHY-201 光模块/光纤收光异常（链式）", [_has("wire_connected"), _has("ethernet_quality_issue"), _has("optical_power_low")], Fact("optical_module_fault"), 100))   # fix_replace_optical_module, fix_clean_fiber_connector
_kb.add_rule(Rule("PHY-202 线缆/水晶头接触不良（链式）", [_has("wire_connected"), _has("ethernet_quality_issue"), _has("crc_error")], Fact("bad_cable_or_connector"), 50))          # fix_replace_cable

# ===================== 链路层/交换 =====================
_kb.add_rule(Rule("L2-001 接口 VLAN 划分错误", [_has("wire_connected"), _has("ping_gateway_fail"), _has("vlan_mismatch")], Fact("wrong_vlan"), 100))                          # fix_correct_vlan
_kb.add_rule(Rule("L2-002 Trunk 未放通网关 VLAN", [_has("wire_connected"), _has("ping_gateway_fail"), _has("trunk_vlan_missing")], Fact("trunk_vlan_not_allowed"), 100))       # fix_allow_vlan_on_trunk
_kb.add_rule(Rule("L2-004 接入口收到 BPDU，缺少生成树保护", [_has("wire_connected"), _has("bpdu_received")], Fact("stp_guard_missing"), 50))                                  # fix_enable_bpduguard
_kb.add_rule(Rule("L2-005 MAC/ARP 表项占满", [_has("wire_connected"), _has("mac_table_full"), _has("intermittent_connectivity")], Fact("mac_table_overflow"), 50))             # fix_set_port_security
_kb.add_rule(Rule("L2-006 链路聚合配置不一致", [_has("wire_connected"), _has("lag_member_down"), _has("bandwidth_insufficient")], Fact("lacp_misconfig"), 50))                # fix_align_lacp_config

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("L2-101 中间事实：二层转发中断", [_has("wire_connected"), _has("link_down"), _has("ping_gateway_fail")], Fact("l2_forwarding_broken"), 60))            # 下游：交换平面过载

# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("L2-102 中间事实：交换平面过载", [_has("wire_connected"), _has("l2_forwarding_broken"), _has("broadcast_storm")], Fact("switch_plane_overload"), 60))  # 下游：STP 环路

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("L2-201 环路导致转发中断（链式）", [_has("wire_connected"), _has("switch_plane_overload"), _has("mac_flapping")], Fact("stp_loop"), 100))                 # fix_enable_stp_bpduguard

# ===================== 网络层 =====================
_kb.add_rule(Rule("NET-001 默认网关配置错误", [_has("wire_connected"), _has("ping_gateway_fail"), _has("wrong_default_gateway")], Fact("wrong_gateway"), 100))                    # fix_correct_gateway
_kb.add_rule(Rule("NET-002 默认网关未配置", [_has("wire_connected"), _has("no_default_gateway"), _has("ping_external_fail")], Fact("missing_gateway"), 100))                     # fix_configure_gateway
_kb.add_rule(Rule("NET-003 网关设备接口故障", [_has("wire_connected"), _has("ping_gateway_fail"), _has("gateway_device_report_error")], Fact("gateway_interface_down"), 100))    # fix_restore_gateway_interface
_kb.add_rule(Rule("NET-004 IP 地址与网关不同网段", [_has("wire_connected"), _has("ping_gateway_fail"), _has("gateway_out_of_subnet")], Fact("subnet_mismatch"), 100))           # fix_correct_ip_or_mask
_kb.add_rule(Rule("NET-006 静态路由缺失", [_has("wire_connected"), _has("can_ping_gateway_only"), _has("no_route_entry")], Fact("missing_route"), 100))                          # fix_add_static_route
_kb.add_rule(Rule("NET-007 回程路由缺失", [_has("wire_connected"), _has("ping_one_way"), _has("asymmetric_routing")], Fact("missing_return_route"), 100))                        # fix_add_return_route
_kb.add_rule(Rule("NET-008 路由环路/TTL 超时", [_has("wire_connected"), _has("traceroute_loop"), _has("ttl_exceeded")], Fact("routing_loop"), 100))                             # fix_remove_routing_loop
_kb.add_rule(Rule("NET-009 路由黑洞（下一跳指向错误设备）", [_has("wire_connected"), _has("no_response_from_dest"), _has("blackhole_route")], Fact("blackhole_route_detected"), 100))     # fix_correct_blackhole_route
_kb.add_rule(Rule("NET-011 IP 地址冲突", [_has("wire_connected"), _has("ip_conflict"), _has("intermittent_connectivity")], Fact("ip_address_conflict"), 100))                    # fix_find_conflicting_host
_kb.add_rule(Rule("NET-012 ARP 欺骗/网关 MAC 被冒充", [_has("wire_connected"), _has("arp_spoofing"), _has("gateway_mac_changed")], Fact("arp_attack"), 100))                    # fix_enable_dai
_kb.add_rule(Rule("NET-013 ARP 表项不完整或过期", [_has("wire_connected"), _has("arp_incomplete"), _has("same_subnet_host_unreachable")], Fact("stale_arp_entry"), 50))          # fix_clear_arp_cache
_kb.add_rule(Rule("NET-014 MTU/MSS 不匹配导致大包丢失", [_has("wire_connected"), _has("ping_small_ok"), _has("ping_large_fail")], Fact("mtu_mismatch"), 50))                     # fix_adjust_mtu_mss
_kb.add_rule(Rule("NET-015 分片被策略丢弃", [_has("wire_connected"), _has("fragmentation_needed"), _has("icmp_blocked")], Fact("fragment_blocked"), 50))                        # fix_allow_fragmentation
_kb.add_rule(Rule("NET-019 出口带宽被打满", [_has("wire_connected"), _has("bandwidth_saturated"), _has("high_latency"), _has("packet_loss")], Fact("bandwidth_congestion"), 50)) # fix_enable_qos, fix_limit_p2p_traffic

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("NET-101 中间事实：三层路径不通", [_has("wire_connected"), _has("same_subnet_host_unreachable")], Fact("l3_path_broken"), 60))                        # 下游：子网掩码 / 网关路由 / NAT
_kb.add_rule(Rule("NET-102 中间事实：跨网段转发失败", [_has("wire_connected"), _has("ping_external_fail"), _has("ping_gateway_ok")], Fact("inter_subnet_forwarding_fail"), 60))  # 下游：NAT / 出口链路

# 链式第 2 层：中间事实 + 现象 → 第二级中间事实
_kb.add_rule(Rule("NET-103 中间事实：NAT 出口异常", [_has("wire_connected"), _has("inter_subnet_forwarding_fail"), _has("nat_pool_exhausted")], Fact("nat_egress_abnormal"), 60))  # 下游：公网出口

# 链式第 2 层：中间事实 + 现象 → 根因
_kb.add_rule(Rule("NET-201 子网掩码配置错误（链式）", [_has("wire_connected"), _has("l3_path_broken"), _has("can_ping_remote_subnet")], Fact("wrong_netmask"), 50))        # fix_correct_netmask
_kb.add_rule(Rule("NET-202 网关路由表未覆盖目标网段（链式）", [_has("wire_connected"), _has("l3_path_broken"), _has("gateway_unreachable_network")], Fact("gateway_route_missing"), 100))  # fix_add_gateway_route
_kb.add_rule(Rule("NET-203 NAT 转换规则异常（链式）", [_has("wire_connected"), _has("inter_subnet_forwarding_fail"), _has("no_nat_translation")], Fact("nat_misconfigured"), 100))   # fix_correct_nat_rule
_kb.add_rule(Rule("NET-205 NAT 地址池耗尽（链式）", [_has("wire_connected"), _has("inter_subnet_forwarding_fail"), _has("nat_pool_exhausted"), _has("intermittent_external_fail")], Fact("nat_pool_exhausted_scope"), 50))  # fix_expand_nat_pool

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("NET-204 公网出口链路故障（链式）", [_has("wire_connected"), _has("nat_egress_abnormal"), _has("isp_link_down")], Fact("isp_fault"), 100))             # fix_contact_isp, fix_switch_backup_link

# ===================== 传输层 =====================
_kb.add_rule(Rule("TCP-001 服务端端口未监听", [_has("wire_connected"), _has("tcp_connect_refused"), _has("service_not_listening")], Fact("service_down"), 100))                    # fix_start_service
_kb.add_rule(Rule("TCP-002 中间设备防火墙丢包（超时而非拒绝）", [_has("wire_connected"), _has("tcp_connect_timeout"), _has("ping_ok"), _has("firewall_drop_rule")], Fact("firewall_blocking"), 100))  # fix_open_firewall_port
_kb.add_rule(Rule("TCP-003 主机防火墙/安全组未放行", [_has("wire_connected"), _has("tcp_connect_timeout"), _has("ping_ok"), _has("host_firewall_enabled")], Fact("host_firewall_blocking"), 100))     # fix_add_host_firewall_rule
_kb.add_rule(Rule("TCP-004 ACL 显式拒绝该流量", [_has("wire_connected"), _has("acl_deny_hit"), _has("ping_gateway_ok")], Fact("acl_blocking"), 100))                            # fix_update_acl
_kb.add_rule(Rule("TCP-005 端口被其他进程占用", [_has("wire_connected"), _has("port_already_in_use"), _has("service_start_failed")], Fact("port_conflict"), 50))                 # fix_kill_conflicting_process
_kb.add_rule(Rule("TCP-006 监听地址绑定错误（只监听 127.0.0.1）", [_has("wire_connected"), _has("telnet_localhost_ok"), _has("telnet_remote_fail")], Fact("listen_address_binding"), 50))  # fix_bind_all_interfaces
_kb.add_rule(Rule("TCP-007 半开连接堆积（SYN 队列满）", [_has("wire_connected"), _has("tcp_handshake_fail"), _has("syn_backlog_full")], Fact("syn_backlog_overflow"), 50))        # fix_increase_backlog, fix_enable_syn_cookies
_kb.add_rule(Rule("TCP-008 连接被对端 RST 重置", [_has("wire_connected"), _has("tcp_reset_by_peer"), _has("idle_timeout")], Fact("rst_from_peer"), 50))                          # fix_increase_session_timeout
_kb.add_rule(Rule("TCP-009 客户端临时端口耗尽", [_has("wire_connected"), _has("ephemeral_port_exhausted"), _has("many_time_wait")], Fact("ephemeral_port_exhaustion"), 50))       # fix_enable_tcp_tw_reuse, fix_use_connection_pool
_kb.add_rule(Rule("TCP-010 QoS 策略限速/丢包", [_has("wire_connected"), _has("qos_drop"), _has("packet_loss"), _has("high_latency")], Fact("qos_limiting"), 50))                   # fix_adjust_qos_policy
_kb.add_rule(Rule("TCP-011 丢包/重传严重", [_has("wire_connected"), _has("packet_loss"), _has("tcp_retransmission_high")], Fact("packet_loss_issue"), 50))                       # fix_investigate_packet_loss

# ===================== 地址分配（DHCP） =====================
_kb.add_rule(Rule("DHCP-001 DHCP 服务器无响应", [_has("wire_connected"), _has("dhcp_no_response"), _has("apipa_address"), _has("no_ip_address")], Fact("dhcp_server_down"), 100))   # fix_restart_dhcp_service, fix_check_dhcp_relay
_kb.add_rule(Rule("DHCP-002 DHCP 地址池耗尽", [_has("wire_connected"), _has("dhcp_pool_exhausted"), _has("intermittent_connectivity")], Fact("dhcp_scope_exhausted"), 100))         # fix_expand_dhcp_pool, fix_shorten_lease_time
_kb.add_rule(Rule("DHCP-003 DHCP 中继(Relay)未配置", [_has("wire_connected"), _has("dhcp_no_response"), _has("dhcp_relay_missing"), _has("cross_subnet")], Fact("dhcp_relay_unconfigured"), 100))  # fix_configure_dhcp_relay
_kb.add_rule(Rule("DHCP-004 获取到错误网段的地址（私接路由器）", [_has("wire_connected"), _has("wrong_dhcp_scope"), _has("gateway_out_of_subnet")], Fact("rogue_dhcp_server"), 100))   # fix_enable_dhcp_snooping

# ===================== 应用层 =====================
_kb.add_rule(Rule("APP-006 HTTP 404 资源或虚拟主机配置错误", [_has("wire_connected"), _has("http_404")], Fact("http_route_or_vhost_error"), 50))                               # fix_check_vhost_config
_kb.add_rule(Rule("APP-011 代理服务器配置错误", [_has("wire_connected"), _has("proxy_config_error"), _has("http_407")], Fact("proxy_misconfigured"), 50))                       # fix_correct_proxy_setting
_kb.add_rule(Rule("APP-012 应用服务器资源耗尽", [_has("wire_connected"), _has("server_cpu_high"), _has("server_memory_high"), _has("http_timeout")], Fact("server_resource_exhaustion"), 100))  # fix_scale_or_restart_app
_kb.add_rule(Rule("APP-013 链路延迟过高导致应用超时", [_has("wire_connected"), _has("high_latency"), _has("http_timeout"), _has("ping_ok")], Fact("latency_too_high"), 50))       # fix_optimize_path_latency

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("APP-101 中间事实：域名解析中断", [_has("wire_connected"), _has("ping_domain_fail")], Fact("name_resolution_broken"), 60))                              # 下游：DNS 各根因
_kb.add_rule(Rule("APP-102 中间事实：上游服务不可用", [_has("wire_connected"), _has("http_502")], Fact("upstream_unavailable"), 60))                                     # 下游：后端健康检查
_kb.add_rule(Rule("APP-103 中间事实：HTTPS 握手失败", [_has("wire_connected"), _has("https_cert_error"), _has("https_connect_fail")], Fact("https_handshake_broken"), 60))  # 下游：证书相关根因

# 链式第 2 层：中间事实 + 现象 → 根因
_kb.add_rule(Rule("APP-001 DNS 域名不存在（链式）", [_has("wire_connected"), _has("name_resolution_broken"), _has("dns_nxdomain")], Fact("dns_record_missing"), 100))          # fix_add_dns_record
_kb.add_rule(Rule("APP-002 DNS 服务器不可达（链式）", [_has("wire_connected"), _has("name_resolution_broken"), _has("dns_timeout")], Fact("dns_server_unreachable"), 100))      # fix_correct_dns_server
_kb.add_rule(Rule("APP-003 DNS 返回 SERVFAIL（链式）", [_has("wire_connected"), _has("name_resolution_broken"), _has("dns_servfail")], Fact("dns_server_misconfigured"), 50))    # fix_check_dns_forwarder
_kb.add_rule(Rule("APP-004 DNS 缓存污染（链式）", [_has("wire_connected"), _has("name_resolution_broken"), _has("dns_wrong_answer")], Fact("dns_cache_poisoned"), 50))           # fix_flush_dns_cache
_kb.add_rule(Rule("APP-201 负载均衡后端健康检查失败（链式）", [_has("wire_connected"), _has("upstream_unavailable"), _has("lb_backend_unhealthy")], Fact("lb_backend_health_check_failed"), 100))  # fix_restore_lb_backend
_kb.add_rule(Rule("APP-202 TLS 证书已过期（链式）", [_has("wire_connected"), _has("https_handshake_broken"), _has("tls_cert_expired")], Fact("certificate_expired"), 100))        # fix_renew_certificate
_kb.add_rule(Rule("APP-203 证书域名不匹配/自签名（链式）", [_has("wire_connected"), _has("https_handshake_broken"), _has("tls_cert_name_mismatch")], Fact("certificate_invalid"), 50))  # fix_use_valid_certificate
_kb.add_rule(Rule("APP-204 后端服务不可用（链式）", [_has("wire_connected"), _has("upstream_unavailable"), _has("http_503")], Fact("upstream_unavailable_scope"), 100))          # fix_check_upstream_service

# ===================== 无线 =====================
_kb.add_rule(Rule("WLAN-001 频繁漫游/掉线", [_has("wireless_client"), _has("roaming_frequent"), _has("link_flapping")], Fact("wifi_roaming_issue"), 50))                            # fix_tune_roaming_threshold
_kb.add_rule(Rule("WLAN-002 仅协商到 2.4G 频段", [_has("wireless_client"), _has("band_24g_only"), _has("bandwidth_insufficient")], Fact("wifi_band_mismatch"), 50))                 # fix_enable_5g_band
_kb.add_rule(Rule("WLAN-003 SSID 隐藏或配置错误", [_has("wireless_client"), _has("ssid_not_found"), _has("cannot_associate")], Fact("ssid_misconfigured"), 50))                     # fix_verify_ssid_config

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("WLAN-101 中间事实：无线链路退化", [_has("wireless_client"), _has("weak_signal"), _has("packet_loss")], Fact("wifi_link_degraded"), 60))                       # 下游：干扰判定

# 链式第 2 层：现象 + 现象 → 中间事实
_kb.add_rule(Rule("WLAN-104 中间事实：怀疑信道干扰", [_has("wireless_client"), _has("wifi_link_degraded"), _has("channel_interference")], Fact("wifi_interference_suspected"), 60))  # 下游：信道干扰 / 信号弱
_kb.add_rule(Rule("WLAN-102 中间事实：无线关联异常", [_has("wireless_client"), _has("wifi_auth_failed"), _has("cannot_associate")], Fact("wifi_association_failed"), 60))           # 下游：认证失败
_kb.add_rule(Rule("WLAN-103 中间事实：无线路径不通", [_has("wireless_client"), _has("ping_gateway_fail"), _has("cannot_associate")], Fact("wireless_path_broken"), 60))            # 下游：AP 侧根因
_kb.add_rule(Rule("WLAN-105 中间事实：认证/关联持续失败", [_has("wireless_client"), _has("wifi_association_failed"), _has("cannot_associate")], Fact("wifi_auth_persist_failed"), 60))  # 下游：认证失败
_kb.add_rule(Rule("WLAN-106 中间事实：AP 侧故障", [_has("wireless_client"), _has("wireless_path_broken"), _has("ap_unreachable")], Fact("wireless_ap_side_fault"), 60))             # 下游：AP 离线

# 链式第 3 层：二级中间事实 + 现象 → 根因
_kb.add_rule(Rule("WLAN-201 信道/同频干扰（链式）", [_has("wireless_client"), _has("wifi_interference_suspected"), _has("channel_interference")], Fact("wifi_channel_interference"), 50))  # fix_switch_to_5g_channel
_kb.add_rule(Rule("WLAN-202 信号强度不足（链式）", [_has("wireless_client"), _has("wifi_interference_suspected"), _has("weak_signal")], Fact("wifi_signal_weak"), 100))           # fix_move_closer_to_ap, fix_add_ap_coverage
_kb.add_rule(Rule("WLAN-203 无线认证失败（链式）", [_has("wireless_client"), _has("wifi_auth_persist_failed"), _has("radius_timeout")], Fact("wifi_auth_failure"), 100))            # fix_reenter_wifi_password, fix_check_radius_server
_kb.add_rule(Rule("WLAN-204 AP 负载过高（链式）", [_has("wireless_client"), _has("wifi_link_degraded"), _has("ap_client_overload")], Fact("ap_overloaded"), 50))                   # fix_enable_band_steering, fix_add_ap
_kb.add_rule(Rule("WLAN-205 AP/无线控制器离线（链式）", [_has("wireless_client"), _has("wireless_ap_side_fault"), _has("ping_gateway_fail")], Fact("ap_offline"), 100))             # fix_restore_ap_power_link

# ===================== VPN/安全策略 =====================
_kb.add_rule(Rule("SEC-001 IPSec 预共享密钥不匹配", [_has("wire_connected"), _has("ipsec_tunnel_down"), _has("psk_mismatch")], Fact("ipsec_psk_mismatch"), 100))                    # fix_align_psk
_kb.add_rule(Rule("SEC-002 IPSec 两阶段提议参数不匹配", [_has("wire_connected"), _has("ipsec_tunnel_down"), _has("proposal_mismatch")], Fact("ipsec_proposal_mismatch"), 100))       # fix_align_ipsec_proposal
_kb.add_rule(Rule("SEC-003 加密算法/证书不被对端接受", [_has("wire_connected"), _has("ipsec_tunnel_down"), _has("crypto_algorithm_mismatch")], Fact("ipsec_crypto_mismatch"), 100))   # fix_align_crypto_suite
_kb.add_rule(Rule("SEC-004 VPN 用户认证失败", [_has("wire_connected"), _has("vpn_auth_failed"), _has("radius_timeout")], Fact("vpn_auth_failure"), 100))                            # fix_check_radius_server
_kb.add_rule(Rule("SEC-006 端口安全/802.1X 认证拦截", [_has("wire_connected"), _has("dot1x_auth_failed"), _has("port_error_disabled")], Fact("dot1x_blocking"), 100))                # fix_check_dot1x_supplicant
_kb.add_rule(Rule("SEC-007 疑似 SYN Flood/异常流量攻击", [_has("wire_connected"), _has("syn_flood_detected"), _has("high_cpu_switch"), _has("tcp_connect_timeout")], Fact("syn_flood_attack"), 100))  # fix_enable_syn_protection
_kb.add_rule(Rule("SEC-008 设备 CPU 被异常流量打高", [_has("wire_connected"), _has("high_cpu_switch"), _has("broadcast_storm")], Fact("control_plane_overload"), 50))                # fix_enable_cpu_protection
_kb.add_rule(Rule("SEC-009 ICMP 被策略禁用（ping 不通但业务正常）", [_has("wire_connected"), _has("icmp_blocked"), _has("tcp_connect_ok")], Fact("icmp_filtered"), 10))                 # fix_allow_icmp_if_needed

# 链式第 1 层：现象 → 中间事实
_kb.add_rule(Rule("SEC-101 中间事实：VPN NAT 环境受限", [_has("wire_connected"), _has("behind_nat_device")], Fact("vpn_nat_environment_limited"), 60))                                # 下游：NAT-T 缺失

# 链式第 2 层：中间事实 + 现象 → 根因
_kb.add_rule(Rule("SEC-201 未启用 NAT 穿越(NAT-T)（链式）", [_has("wire_connected"), _has("vpn_nat_environment_limited"), _has("ipsec_tunnel_down")], Fact("nat_traversal_missing"), 50))  # fix_enable_nat_t
