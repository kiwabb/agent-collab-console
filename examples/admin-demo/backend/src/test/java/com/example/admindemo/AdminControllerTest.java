package com.example.admindemo;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
class AdminControllerTest {
    @Autowired private MockMvc mockMvc;

    @Test void readinessReturnsStableApplicationIdentity() throws Exception {
        mockMvc.perform(get("/api/health/ready"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.service").value("admin-demo-backend"))
                .andExpect(jsonPath("$.status").value("ready"));
    }

    @Test void dashboardReturnsMetrics() throws Exception {
        mockMvc.perform(get("/api/dashboard")).andExpect(status().isOk()).andExpect(jsonPath("$.totalUsers").value(2846));
    }

    @Test void usersReturnsUserList() throws Exception {
        mockMvc.perform(get("/api/users")).andExpect(status().isOk()).andExpect(jsonPath("$[0].email").value("xiaoning.chen@example.com"));
    }

    @Test void ordersReturnsOrderList() throws Exception {
        mockMvc.perform(get("/api/orders")).andExpect(status().isOk()).andExpect(jsonPath("$[0].status").value("paid"));
    }
}
